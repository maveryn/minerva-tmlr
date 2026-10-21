from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from .models import PaperAsset, PaperAuthor, PaperManifest, PaperSection


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf")
TEXT_EXTENSIONS = (".tex", ".bib", ".bbl")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_availability_sentence(text: str) -> str:
    patterns = (
        r"\s*(?:Project page,\s*)?(?:Code|Data|Dataset|Project page, code, and dataset|Project page, code and dataset|Code and dataset|Code, data,? and dataset)[^.]*available at\s+\S+\.?\s*$",
        r"\s*(?:Project page,\s*)?(?:Code|Data|Dataset|Project page, code, and dataset|Project page, code and dataset|Code and dataset|Code, data,? and dataset)[^.]*available (?:on|from)\s+\S+\.?\s*$",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _clean_latex(text: str) -> str:
    cleaned = text
    cleaned = cleaned.replace("\\and", "\n")
    cleaned = cleaned.replace("\\\\", "\n")
    cleaned = cleaned.replace("~", " ")
    for src, dest in (
        ("\\%", "%"),
        ("\\&", "&"),
        ("\\_", "_"),
        ("\\$", "$"),
        ("\\#", "#"),
    ):
        cleaned = cleaned.replace(src, dest)
    cleaned = re.sub(
        r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|citeyearpar)\*?(?:\[[^\]]*\])?(?:\[[^\]]*\])?\{[^{}]*\}",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\\(?:ref|eqref|autoref|pageref)\{[^{}]*\}", "", cleaned)
    cleaned = re.sub(r"\\(?:url|href)\{([^{}]*)\}(?:\{([^{}]*)\})?", lambda m: m.group(2) or m.group(1), cleaned)

    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = re.sub(
            r"\\(?:textbf|textit|emph|textsc|tt|small|footnotesize|mathrm|mathbf|mathit|textrm)\{([^{}]*)\}",
            r"\1",
            cleaned,
        )
        cleaned = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z*]+", " ", cleaned)
    cleaned = cleaned.replace("{", " ").replace("}", " ")
    cleaned = _normalize_ws(cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    return cleaned


def _extract_braced_content(text: str, open_brace_index: int) -> tuple[str, int] | None:
    if open_brace_index >= len(text) or text[open_brace_index] != "{":
        return None

    depth = 0
    body: list[str] = []
    index = open_brace_index
    while index < len(text):
        char = text[index]

        if (
            char == "\\"
            and index + 1 < len(text)
            and text[index + 1] in "{}"
            and (index == 0 or text[index - 1] != "\\")
        ):
            if depth >= 1:
                body.extend([char, text[index + 1]])
            index += 2
            continue

        if char == "{":
            depth += 1
            if depth > 1:
                body.append(char)
            index += 1
            continue

        if char == "}":
            depth -= 1
            if depth == 0:
                return "".join(body), index + 1
            body.append(char)
            index += 1
            continue

        if depth >= 1:
            body.append(char)
        index += 1

    return None


def _extract_command_body(text: str, command: str) -> str:
    bodies = _extract_command_bodies(text, command)
    return bodies[0] if bodies else ""


def _extract_command_bodies(text: str, command: str) -> list[str]:
    pattern = re.compile(rf"\\{command}\s*(?:\[[^\]]*\]\s*)?\{{", re.DOTALL)
    bodies: list[str] = []
    search_start = 0
    while True:
        match = pattern.search(text, search_start)
        if not match:
            return bodies
        result = _extract_braced_content(text, match.end() - 1)
        if not result:
            return bodies
        body, end_index = result
        bodies.append(body)
        search_start = end_index


def _extract_braced_command(text: str, command: str) -> str:
    return _clean_latex(_extract_command_body(text, command))


def _extract_environment(text: str, name: str) -> str:
    pattern = re.compile(rf"\\begin\{{{name}\}}(?P<body>.*?)\\end\{{{name}\}}", re.DOTALL)
    match = pattern.search(text)
    if not match:
        return ""
    return _clean_latex(match.group("body"))


def _extract_caption(block: str) -> str:
    captions = _extract_command_bodies(block, "caption")
    if not captions:
        return ""
    return _clean_latex(captions[-1])


def _extract_authors(text: str) -> list[str]:
    parsed = _extract_author_metadata(text)
    return parsed["authors"]


def _extract_author_metadata(text: str) -> dict[str, list[str]]:
    body = _extract_command_body(text, "author")
    if not body:
        return {"authors": [], "affiliations": [], "author_entries": []}

    body = body.replace("\\\\", "\n")
    # TMLR places emails on the name line and separates author blocks with AND.
    body = re.sub(r"\\email\s+[^\n]*", "", body)
    chunks = re.split(r"\\(?:TMLRauthorAND|AND|and)\b", body)
    authors = []
    affiliations: list[str] = []
    author_entries: list[PaperAuthor] = []
    for chunk in chunks:
        lines = [_clean_latex(line) for line in chunk.splitlines()]
        lines = [line for line in lines if line]
        if lines:
            author_name = lines[0]
            authors.append(author_name)
            author_affiliations: list[str] = []
            for line in lines[1:]:
                normalized = line.strip()
                if "@" in normalized:
                    continue
                if normalized.lower() in {"equal contribution", "*indicates equal contribution"}:
                    continue
                if normalized not in affiliations:
                    affiliations.append(normalized)
                if normalized not in author_affiliations:
                    author_affiliations.append(normalized)
                break
            author_entries.append(
                PaperAuthor(
                    name=author_name,
                    affiliations=author_affiliations,
                    affiliation_indices=[],
                )
            )

    affiliation_index = {affiliation: index + 1 for index, affiliation in enumerate(affiliations)}
    for entry in author_entries:
        entry.affiliation_indices = [affiliation_index[item] for item in entry.affiliations if item in affiliation_index]

    return {"authors": authors, "affiliations": affiliations, "author_entries": author_entries}


def _derive_summary(abstract: str) -> str:
    if not abstract:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", abstract.strip())
    if not sentences:
        return ""
    return " ".join(sentences[:2]).strip()


def _derive_section_summary(text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return ""
    return " ".join(sentences[:3]).strip()


def _resolve_candidate(target: str, *search_roots: Path) -> Path | None:
    checked: list[Path] = []
    for root in search_roots:
        if root in checked:
            continue
        checked.append(root)

        raw = (root / target).resolve()
        if raw.is_file():
            return raw
        if raw.suffix:
            continue
        for ext in IMAGE_EXTENSIONS + TEXT_EXTENSIONS:
            candidate = raw.with_suffix(ext)
            if candidate.is_file():
                return candidate
    return None


def _find_main_tex(source_dir: Path, explicit_main: str | None = None) -> Path:
    if explicit_main:
        explicit = (source_dir / explicit_main).resolve()
        if explicit.is_file():
            return explicit
        raise FileNotFoundError(f"Explicit main tex not found: {explicit_main}")

    tex_files = sorted(source_dir.rglob("*.tex"))
    if not tex_files:
        raise FileNotFoundError(f"No .tex files found under {source_dir}")

    def score(path: Path) -> int:
        text = _read_text(path)
        rel = path.relative_to(source_dir).as_posix()
        value = 0
        if path.name in {"main.tex", "paper.tex", "main_cvpr.tex"}:
            value += 60
        if "\\documentclass" in text:
            value += 40
        if "\\begin{document}" in text:
            value += 30
        value += min(text.count("\\input{") + text.count("\\include{"), 6) * 5
        if rel.count("/") == 0:
            value += 10
        return value

    return max(tex_files, key=score)


def _collect_tex_graph(source_dir: Path, main_tex: Path) -> dict[Path, str]:
    seen: dict[Path, str] = {}

    def visit(path: Path) -> None:
        if path in seen:
            return
        text = _strip_comments(_read_text(path))
        seen[path] = text
        includes = re.findall(r"\\(?:input|include)\{([^}]+)\}", text)
        for target in includes:
            candidate = _resolve_candidate(target, path.parent, main_tex.parent, source_dir)
            if candidate and candidate.suffix == ".tex":
                visit(candidate)

    visit(main_tex)
    return seen


def _strip_display_environments(text: str) -> str:
    stripped = text
    for env in ("figure", "figure*", "table", "table*", "tabular", "tabular*", "align", "equation"):
        stripped = re.sub(
            rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}",
            "\n",
            stripped,
            flags=re.DOTALL,
        )
    return stripped


def _extract_section_summary(text: str) -> str:
    stripped = _strip_display_environments(text)
    stripped = re.sub(r"\\(?:section|subsection|subsubsection)\*?\{[^}]+\}", "\n", stripped)
    stripped = re.sub(r"\\input\{[^}]+\}", "\n", stripped)
    paragraphs = re.split(r"\n\s*\n", stripped)
    for paragraph in paragraphs:
        cleaned = _clean_latex(paragraph)
        if len(cleaned.split()) >= 12:
            return _derive_section_summary(cleaned)
    return ""


def _extract_sections(
    tex_graph: dict[Path, str], source_dir: Path, main_tex: Path
) -> tuple[list[str], list[PaperSection]]:
    section_inputs: list[str] = []
    sections: list[PaperSection] = []
    main_rel = main_tex.relative_to(source_dir).as_posix()
    for path, text in tex_graph.items():
        rel = path.relative_to(source_dir).as_posix()
        if rel != main_rel:
            section_inputs.append(rel)
        for match in re.finditer(r"\\section\*?\{([^}]+)\}", text):
            sections.append(
                PaperSection(
                    title=_clean_latex(match.group(1)),
                    source=rel,
                    summary=_extract_section_summary(text),
                )
            )
    dedup_inputs = list(dict.fromkeys(section_inputs))
    return dedup_inputs, sections


def _figure_score(path: Path, source: str = "", caption: str = "", section_title: str = "") -> int:
    name = path.as_posix().lower()
    score = 0
    caption_text = f"{caption} {section_title}".lower()
    preferred = (
        "teaser",
        "overview",
        "intro",
        "radar",
        "qualitative",
        "hero",
        "figure1",
        "benchmark",
        "analysis",
        "gallery",
        "illustration",
        "human_eval",
    )
    discouraged = ("appendix", "supp", "supplement", "ablation", "sample_", "task_examples")
    for token in preferred:
        if token in name:
            score += 10
    for token in discouraged:
        if token in name:
            score -= 6
    if "appendix" in source.lower():
        score -= 8
    if any(token in caption_text for token in ("benchmark", "accuracy", "comparison", "overview", "task", "results")):
        score += 4
    if any(token in caption_text for token in ("per-task", "between", "outperform", "achieves")):
        score += 4
    if "_vs_" in name or "vs_" in name or "_vs" in name:
        score += 3
    if "sample_" in name:
        score -= 4
    if caption.lower().startswith("example "):
        score -= 6
    return score


def _extract_figures(tex_graph: dict[Path, str], source_dir: Path, main_tex: Path) -> list[PaperAsset]:
    assets: list[PaperAsset] = []
    seen: set[Path] = set()
    for tex_path, text in tex_graph.items():
        section_markers = list(re.finditer(r"\\section\*?\{([^}]+)\}", text))
        figure_blocks = list(
            re.finditer(r"\\begin\{figure\*?\}(?:\[[^\]]*\])?(.*?)\\end\{figure\*?\}", text, re.DOTALL)
        )
        handled_spans: list[tuple[int, int]] = []

        for block_match in figure_blocks:
            block = block_match.group(1)
            handled_spans.append((block_match.start(), block_match.end()))
            caption = _extract_caption(block)
            section_title = ""
            for marker in section_markers:
                if marker.start() < block_match.start():
                    section_title = _clean_latex(marker.group(1))
                else:
                    break
            if not section_title and section_markers:
                section_title = _clean_latex(section_markers[0].group(1))

            for image_match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", block):
                target = image_match.group(1)
                candidate = _resolve_candidate(target, tex_path.parent, main_tex.parent, source_dir)
                if not candidate or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                assets.append(
                    PaperAsset(
                        path=candidate.relative_to(source_dir).as_posix(),
                        source=tex_path.relative_to(source_dir).as_posix(),
                        score=_figure_score(
                            candidate,
                            source=tex_path.relative_to(source_dir).as_posix(),
                            caption=caption,
                            section_title=section_title,
                        ),
                        caption=caption,
                        section_title=section_title,
                    )
                )

        for match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text):
            if any(start <= match.start() < end for start, end in handled_spans):
                continue
            target = match.group(1)
            candidate = _resolve_candidate(target, tex_path.parent, main_tex.parent, source_dir)
            if not candidate or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            section_title = ""
            for marker in section_markers:
                if marker.start() < match.start():
                    section_title = _clean_latex(marker.group(1))
                else:
                    break
            if not section_title and section_markers:
                section_title = _clean_latex(section_markers[0].group(1))
            assets.append(
                PaperAsset(
                    path=candidate.relative_to(source_dir).as_posix(),
                    source=tex_path.relative_to(source_dir).as_posix(),
                    score=_figure_score(
                        candidate,
                        source=tex_path.relative_to(source_dir).as_posix(),
                        section_title=section_title,
                    ),
                    section_title=section_title,
                )
            )
    return sorted(assets, key=lambda item: (-item.score, item.path))


def _table_score(source: str = "", caption: str = "", section_title: str = "") -> int:
    text = f"{caption} {section_title}".lower()
    score = 0
    if "appendix" in source.lower():
        score -= 8
    if any(token in text for token in ("benchmark", "results", "accuracy", "performance", "evaluation")):
        score += 10
    if any(token in text for token in ("ablation", "hyperparameter", "supplement")):
        score -= 4
    return score


def _extract_tables(tex_graph: dict[Path, str], source_dir: Path) -> list[PaperAsset]:
    assets: list[PaperAsset] = []
    for tex_path, text in tex_graph.items():
        section_markers = list(re.finditer(r"\\section\*?\{([^}]+)\}", text))
        table_blocks = list(re.finditer(r"\\begin\{table\*?\}(?:\[[^\]]*\])?(.*?)\\end\{table\*?\}", text, re.DOTALL))
        for index, block_match in enumerate(table_blocks, start=1):
            block = block_match.group(1)
            caption = _extract_caption(block)
            if not caption:
                continue
            section_title = ""
            for marker in section_markers:
                if marker.start() < block_match.start():
                    section_title = _clean_latex(marker.group(1))
                else:
                    break
            if not section_title and section_markers:
                section_title = _clean_latex(section_markers[0].group(1))
            assets.append(
                PaperAsset(
                    path=f"{tex_path.relative_to(source_dir).as_posix()}::table-{index}",
                    source=tex_path.relative_to(source_dir).as_posix(),
                    kind="table",
                    score=_table_score(
                        source=tex_path.relative_to(source_dir).as_posix(),
                        caption=caption,
                        section_title=section_title,
                    ),
                    caption=caption,
                    section_title=section_title,
                )
            )
    return sorted(assets, key=lambda item: (-item.score, item.path))


def _extract_bibliography_files(main_text: str, source_dir: Path) -> list[str]:
    files = []
    for match in re.finditer(r"\\bibliography\{([^}]+)\}", main_text):
        for target in match.group(1).split(","):
            candidate = _resolve_candidate(target.strip(), source_dir)
            if candidate and candidate.suffix == ".bib":
                files.append(candidate.relative_to(source_dir).as_posix())
    return list(dict.fromkeys(files))


def _infer_venue(text: str) -> str:
    for pattern in (
        r"\\def\\confName\{([^}]+)\}",
        r"\\conference\{([^}]+)\}",
        r"(NeurIPS\s+\d{4})",
        r"(CVPR\s+\d{4})",
        r"(ICLR\s+\d{4})",
    ):
        match = re.search(pattern, text)
        if match:
            return _clean_latex(match.group(1))
    return ""


def _infer_year(text: str) -> str:
    for pattern in (r"\\def\\confYear\{([^}]+)\}", r"\b(20\d{2})\b"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _prepare_source_dir(paper_path: str | Path) -> Path:
    path = Path(paper_path).resolve()
    if path.is_dir():
        return path
    if path.suffix.lower() != ".zip":
        raise ValueError(f"Unsupported paper input: {path}")

    tmpdir = Path(tempfile.mkdtemp(prefix="paperpage-"))
    with zipfile.ZipFile(path) as zf:
        zf.extractall(tmpdir)
    return tmpdir


def extract_paper_bundle(paper_path: str | Path, main_tex: str | None = None) -> PaperManifest:
    source_dir = _prepare_source_dir(paper_path)
    main_file = _find_main_tex(source_dir, explicit_main=main_tex)
    tex_graph = _collect_tex_graph(source_dir, main_file)
    # Metadata may be in input files, including a one-line wrapper entrypoint.
    def expand_inputs(path: Path, active: frozenset[Path] = frozenset()) -> str:
        if path in active:
            return ""
        def expand(match: re.Match[str]) -> str:
            target = _resolve_candidate(match.group(1), path.parent, main_file.parent, source_dir)
            if target in tex_graph:
                return expand_inputs(target, active | {path})
            return match.group(0)
        return re.sub(r"\\(?:input|include)\{([^}]+)\}", expand, tex_graph[path])
    main_text = expand_inputs(main_file)
    author_metadata = _extract_author_metadata(main_text)
    section_inputs, sections = _extract_sections(tex_graph, source_dir, main_file)
    figure_assets = _extract_figures(tex_graph, source_dir, main_file)
    table_assets = _extract_tables(tex_graph, source_dir)
    bibliography_files = _extract_bibliography_files(main_text, source_dir)

    candidate_hero_assets = [asset.path for asset in figure_assets[:4]]
    abstract = _strip_availability_sentence(_extract_environment(main_text, "abstract"))
    return PaperManifest(
        paper_path=str(Path(paper_path).resolve()),
        source_dir=str(source_dir),
        main_tex=main_file.relative_to(source_dir).as_posix(),
        title=_extract_braced_command(main_text, "title"),
        authors=author_metadata["authors"],
        affiliations=author_metadata["affiliations"],
        author_entries=author_metadata["author_entries"],
        abstract=abstract,
        summary=_derive_summary(abstract),
        venue=_infer_venue(main_text),
        year=_infer_year(main_text),
        section_inputs=section_inputs,
        sections=sections,
        figure_assets=figure_assets,
        table_assets=table_assets,
        bibliography_files=bibliography_files,
        candidate_hero_assets=candidate_hero_assets,
    )
