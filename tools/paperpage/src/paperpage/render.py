from __future__ import annotations

from importlib import resources
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageChops
import yaml

from .models import BuildArtifacts, PaperManifest


def _asset_exists(manifest: PaperManifest, rel_path: str, configured_assets: set[str] | None = None) -> bool:
    if configured_assets and rel_path in configured_assets:
        return True
    return (Path(manifest.source_dir) / rel_path).is_file()


def _preferred_gallery_candidates(manifest: PaperManifest) -> list[str]:
    main_assets = [asset.path for asset in manifest.figure_assets if not asset.source.startswith("appendix/")]
    if main_assets:
        return main_assets
    return [asset.path for asset in manifest.figure_assets]


def _select_gallery_assets(manifest: PaperManifest, resolved: dict, configured_assets: set[str] | None = None) -> list[str]:
    requested = resolved.get("hero", {}).get("figure")
    explicit_story_assets = resolved.get("story", {}).get("figures", [])
    explicit_story_sections = resolved.get("story", {}).get("sections", [])
    gallery_limit = int(resolved.get("gallery", {}).get("max_items", 4))
    explicit_section_figures = []
    for item in explicit_story_sections:
        if isinstance(item, dict):
            explicit_section_figures.extend(item.get("figures", []) or [])
    gallery_limit = max(gallery_limit, len(explicit_story_assets) + len(explicit_section_figures) + 1)
    if not explicit_story_assets:
        gallery_limit = max(gallery_limit, int(resolved.get("story", {}).get("max_items", 6)) + 1)
    available = _preferred_gallery_candidates(manifest)

    selected: list[str] = []
    if requested and _asset_exists(manifest, requested, configured_assets):
        selected.append(requested)

    for path in explicit_story_assets:
        if not _asset_exists(manifest, path, configured_assets):
            continue
        if path not in selected:
            selected.append(path)
        if len(selected) >= gallery_limit:
            break

    for path in explicit_section_figures:
        if not _asset_exists(manifest, path, configured_assets):
            continue
        if path not in selected:
            selected.append(path)
        if len(selected) >= gallery_limit:
            break

    for item in explicit_story_sections:
        if len(selected) >= gallery_limit:
            break
        if isinstance(item, str):
            ref = item.strip().lower()
        else:
            figure_refs = item.get("figures", []) or []
            if figure_refs:
                continue
            ref = str(item.get("title", "")).strip().lower()
        if not ref:
            continue

        matching_assets = []
        for asset in manifest.figure_assets:
            if asset.source.startswith("appendix/"):
                continue
            title = asset.section_title.lower()
            source_title = f"{asset.source.lower()}::{title}"
            if title == ref or source_title == ref or ref in title:
                matching_assets.append(asset)
        if not matching_assets:
            continue

        path = max(matching_assets, key=lambda asset: asset.score).path
        if _asset_exists(manifest, path, configured_assets) and path not in selected:
            selected.append(path)

    for path in available:
        if path not in selected:
            selected.append(path)
        if len(selected) >= gallery_limit:
            break

    for path in manifest.candidate_hero_assets:
        if not _asset_exists(manifest, path, configured_assets):
            continue
        if path not in selected:
            selected.append(path)
        if len(selected) >= gallery_limit:
            break
    return selected[:gallery_limit]


def _copy_selected_assets(
    manifest: PaperManifest, selected_assets: list[str], docs_dir: Path, configured_assets: set[str] | None = None
) -> list[str]:
    copied = []
    source_root = Path(manifest.source_dir)
    target_dir = docs_dir / "assets" / "figures"
    target_dir.mkdir(parents=True, exist_ok=True)

    for rel in selected_assets:
        if configured_assets and rel in configured_assets and (docs_dir / rel).is_file():
            copied.append(rel)
            continue

        src = source_root / rel
        if not src.is_file():
            continue
        if src.suffix.lower() == ".pdf":
            dest = target_dir / f"{src.stem}.png"
            _render_pdf_page(src, page=1, dpi=220).save(dest)
        else:
            dest = target_dir / src.name
            shutil.copy2(src, dest)
        copied.append((Path("assets") / "figures" / dest.name).as_posix())
    return copied


def _build_story_blocks(
    manifest: PaperManifest,
    resolved: dict,
    copied_assets: list[str],
    hero_asset: str | None = None,
) -> list[dict]:
    explicit_story_assets = resolved.get("story", {}).get("figures", [])
    explicit_story_sections = resolved.get("story", {}).get("sections", [])
    if explicit_story_assets:
        return _build_explicit_story_blocks(manifest, resolved, copied_assets, hero_asset=hero_asset)
    if explicit_story_sections:
        return _build_configured_story_blocks(manifest, explicit_story_sections, copied_assets)
    return _build_auto_story_blocks(manifest, resolved, copied_assets, hero_asset=hero_asset)


def _build_explicit_story_blocks(
    manifest: PaperManifest,
    resolved: dict,
    copied_assets: list[str],
    hero_asset: str | None = None,
) -> list[dict]:
    max_items = int(resolved.get("story", {}).get("max_items", 3))
    blocks = []
    pool = [path for path in copied_assets if path != hero_asset]
    for copied_path in pool[:max_items]:
        copied_name = Path(copied_path).name
        copied_stem = Path(copied_path).stem
        match = next(
            (
                asset
                for asset in manifest.figure_assets
                if Path(asset.path).name == copied_name or Path(asset.path).stem == copied_stem
            ),
            None,
        )
        if not match:
            continue
        title = match.section_title or "Visual Result"
        body = match.caption or f"Selected figure from {match.source}"
        blocks.append(
            {
                "title": title,
                "body": body,
                "asset_kind": "figure",
                "asset_image": copied_path,
                "asset_caption": match.caption,
            }
        )
    return blocks


def _collect_section_rows(manifest: PaperManifest) -> list[dict]:
    rows = []
    for section in manifest.sections:
        if section.source.startswith("appendix/"):
            continue
        section_figures = [
            asset
            for asset in manifest.figure_assets
            if asset.source == section.source and asset.section_title == section.title
        ]
        section_tables = [
            asset
            for asset in manifest.table_assets
            if asset.source == section.source and asset.section_title == section.title
        ]
        rows.append(
            {
                "title": section.title,
                "source": section.source,
                "summary": section.summary,
                "figure": max(section_figures, key=lambda asset: asset.score, default=None),
                "table": max(section_tables, key=lambda asset: asset.score, default=None),
            }
        )
    return rows


def _find_configured_section(section_rows: list[dict], ref: str) -> dict | None:
    normalized_ref = ref.strip().lower()
    if not normalized_ref:
        return None

    if "::" in normalized_ref:
        source_ref, title_ref = normalized_ref.split("::", 1)
        for row in section_rows:
            if row["source"].lower() == source_ref and row["title"].lower() == title_ref:
                return row

    for row in section_rows:
        if row["title"].lower() == normalized_ref:
            return row

    for row in section_rows:
        if normalized_ref in row["title"].lower():
            return row
    return None


def _resolve_copied_images(figure_refs: list[str], copied_lookup: dict[str, str]) -> list[str]:
    images: list[str] = []
    for ref in figure_refs:
        stem = Path(ref).stem
        copied = copied_lookup.get(stem)
        if copied and copied not in images:
            images.append(copied)
    return images


def _build_story_block_from_row(
    row: dict,
    copied_lookup: dict[str, str],
    preferred_kind: str | None = None,
    title_override: str | None = None,
    body_override: str | None = None,
    figure_refs: list[str] | None = None,
    layout: str | None = None,
    details: dict | None = None,
) -> dict:
    title = title_override or row["title"]
    body = body_override or row["summary"] or ""
    explicit_images = _resolve_copied_images(figure_refs or [], copied_lookup)
    if explicit_images:
        return {
            "title": title,
            "body": body,
            "asset_kind": "figure",
            "asset_images": explicit_images,
            "asset_image": explicit_images[0],
            "layout": layout or ("stacked" if len(explicit_images) > 1 else "split"),
            "details": details or {},
        }

    if preferred_kind == "text":
        return {
            "title": title,
            "body": body,
            "asset_kind": "text",
            "layout": layout or "split",
            "details": details or {},
        }

    if preferred_kind == "table" and row.get("table"):
        return {
            "title": title,
            "body": body or row["table"].caption,
            "asset_kind": "table",
            "asset_caption": row["table"].caption,
            "layout": layout or "split",
            "details": details or {},
        }

    if preferred_kind == "figure" and row.get("figure"):
        copied_path = copied_lookup.get(Path(row["figure"].path).stem)
        if copied_path:
            return {
                "title": title,
                "body": body or row["figure"].caption,
                "asset_kind": "figure",
                "asset_images": [copied_path],
                "asset_image": copied_path,
                "asset_caption": row["figure"].caption,
                "layout": layout or "split",
                "details": details or {},
            }

    if row.get("table") and (not row.get("figure") or row["table"].score >= row["figure"].score):
        return {
            "title": title,
            "body": body or row["table"].caption,
            "asset_kind": "table",
            "asset_caption": row["table"].caption,
            "layout": layout or "split",
            "details": details or {},
        }

    if row.get("figure"):
        copied_path = copied_lookup.get(Path(row["figure"].path).stem)
        if copied_path:
            return {
                "title": title,
                "body": body or row["figure"].caption,
                "asset_kind": "figure",
                "asset_images": [copied_path],
                "asset_image": copied_path,
                "asset_caption": row["figure"].caption,
                "layout": layout or "split",
                "details": details or {},
            }

    return {
        "title": title,
        "body": body,
        "asset_kind": "text",
        "layout": layout or "split",
        "details": details or {},
    }


def _build_configured_story_blocks(
    manifest: PaperManifest, configured_sections: list[str | dict], copied_assets: list[str]
) -> list[dict]:
    copied_lookup = {Path(path).stem: path for path in copied_assets}
    section_rows = _collect_section_rows(manifest)
    blocks = []
    for item in configured_sections:
        if isinstance(item, str):
            ref = item
            preferred_kind = None
            heading = None
            body_override = None
            figure_refs = []
            layout = None
            details = {}
        else:
            ref = str(item.get("title", "")).strip()
            preferred_kind = item.get("evidence")
            heading = item.get("heading")
            body_override = item.get("body")
            figure_refs = item.get("figures", []) or []
            layout = item.get("layout")
            details = item.get("details") or {}
        row = _find_configured_section(section_rows, ref)
        if not row:
            continue
        blocks.append(
            _build_story_block_from_row(
                row,
                copied_lookup,
                preferred_kind=preferred_kind,
                title_override=heading,
                body_override=body_override,
                figure_refs=figure_refs,
                layout=layout,
                details=details,
            )
        )
    return blocks


def _score_section(section: dict, hero_title: str) -> int:
    title = section["title"].lower()
    score = 0
    if title in {"introduction", "related work", "related works", "conclusion", "limitations & future work"}:
        score -= 100
    preferred = {
        "benchmark": 18,
        "results": 16,
        "analysis": 15,
        "evaluation": 14,
        "reinforcement learning": 15,
        "experiments": 14,
        "method": 13,
        "approach": 13,
        "dataset": 12,
        "design": 10,
    }
    for token, value in preferred.items():
        if token in title:
            score += value
    if hero_title and hero_title.lower() == title:
        score -= 8
    if section.get("summary"):
        score += 5
    if section.get("figure"):
        score += max(section["figure"].score, 0)
    if section.get("table"):
        score += max(section["table"].score, 0) + 4
    return score


def _build_auto_story_blocks(
    manifest: PaperManifest,
    resolved: dict,
    copied_assets: list[str],
    hero_asset: str | None = None,
) -> list[dict]:
    min_items = int(resolved.get("story", {}).get("min_items", 3))
    max_items = int(resolved.get("story", {}).get("max_items", 6))
    copied_lookup = {Path(path).stem: path for path in copied_assets if path != hero_asset}

    hero_title = ""
    if hero_asset:
        hero_stem = Path(hero_asset).stem
        hero_match = next(
            (asset for asset in manifest.figure_assets if Path(asset.path).stem == hero_stem),
            None,
        )
        hero_title = hero_match.section_title if hero_match else ""

    section_rows = [
        row for row in _collect_section_rows(manifest) if row.get("summary") or row.get("figure") or row.get("table")
    ]

    ranked = sorted(section_rows, key=lambda row: _score_section(row, hero_title), reverse=True)
    if not ranked:
        return []

    selected = [row for row in ranked if _score_section(row, hero_title) >= 10][:max_items]
    if len(selected) < min_items:
        selected = ranked[: min(max_items, max(min_items, len(ranked)))]
    selected = sorted(selected, key=lambda row: section_rows.index(row))

    blocks = []
    for row in selected[:max_items]:
        blocks.append(_build_story_block_from_row(row, copied_lookup))
    return blocks


def _copy_theme_assets(theme_name: str, docs_dir: Path) -> None:
    static_root = resources.files("paperpage").joinpath("templates").joinpath(theme_name).joinpath("static")
    if not static_root.is_dir():
        return

    target_root = docs_dir / "static"
    target_root.mkdir(parents=True, exist_ok=True)

    for item in static_root.iterdir():
        if item.is_dir():
            shutil.copytree(item, target_root / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target_root / item.name)


def _resolve_source_path(
    source_value: str,
    source_root: Path,
    project_config_dir: str | None = None,
    user_config_dir: str | None = None,
) -> Path:
    src = Path(source_value)
    if src.is_absolute():
        return src

    candidates: list[Path] = []
    if project_config_dir:
        candidates.append((Path(project_config_dir) / source_value).resolve())
    if user_config_dir:
        candidates.append((Path(user_config_dir) / source_value).resolve())
    candidates.append((source_root / source_value).resolve())
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[-1])


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


def _strip_latex_command(text: str, command: str) -> str:
    pattern = re.compile(rf"\\{command}(?:\[[^\]]*\])?\s*\{{", re.DOTALL)
    cleaned = text
    while True:
        match = pattern.search(cleaned)
        if not match:
            return cleaned
        brace_index = cleaned.find("{", match.start())
        result = _extract_braced_content(cleaned, brace_index)
        if not result:
            return cleaned
        _, end_index = result
        cleaned = cleaned[: match.start()] + cleaned[end_index:]


def _render_pdf_page(source: Path, page: int, dpi: int) -> Image.Image:
    pdf_converter = shutil.which("pdftocairo")
    if pdf_converter:
        with tempfile.TemporaryDirectory(prefix="paperpage-pdf-") as tmpdir:
            out_prefix = Path(tmpdir) / "page"
            subprocess.run(
                [
                    pdf_converter,
                    "-singlefile",
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    str(source),
                    str(out_prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return Image.open(out_prefix.with_suffix(".png")).convert("RGB")

    ghostscript = shutil.which("gs")
    if ghostscript:
        with tempfile.TemporaryDirectory(prefix="paperpage-pdf-") as tmpdir:
            out_path = Path(tmpdir) / "page.png"
            subprocess.run(
                [
                    ghostscript,
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-sDEVICE=png16m",
                    f"-r{dpi}",
                    f"-dFirstPage={page}",
                    f"-dLastPage={page}",
                    f"-sOutputFile={out_path}",
                    str(source),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return Image.open(out_path).convert("RGB")

    # PDFium also works on Windows without a system Poppler/Ghostscript install.
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("Install pypdfium2, pdftocairo, or gs to render PDF assets") from exc
    with pdfium.PdfDocument(str(source)) as document:
        pdf_page = document[page - 1]
        try:
            bitmap = pdf_page.render(scale=dpi / 72)
            try:
                return bitmap.to_pil().convert("RGB").copy()
            finally:
                bitmap.close()
        finally:
            pdf_page.close()


def _box_to_pixels(box: list[float], image: Image.Image, unit: str) -> tuple[int, int, int, int]:
    width, height = image.size
    if unit == "pixels":
        left, top, right, bottom = [int(value) for value in box]
        return left, top, right, bottom

    left = int(box[0] * width)
    top = int(box[1] * height)
    right = int(box[2] * width)
    bottom = int(box[3] * height)
    return left, top, right, bottom


def _trim_whitespace(image: Image.Image) -> Image.Image:
    background = Image.new(image.mode, image.size, "white")
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def _load_image_asset(source: Path) -> Image.Image:
    if source.suffix.lower() == ".pdf":
        return _render_pdf_page(source, page=1, dpi=220)
    image = Image.open(source)
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, image.convert("RGBA")).convert("RGB")
    return image.convert("RGB")


def _compose_images(
    sources: list[Path],
    layout: str = "row",
    gap: int = 16,
    padding: int = 16,
    background: str = "white",
) -> Image.Image:
    images = [_load_image_asset(source) for source in sources]
    if not images:
        raise ValueError("No sources provided for composite image")

    if layout == "column":
        target_width = max(image.size[0] for image in images)
        resized = []
        for image in images:
            if image.size[0] == target_width:
                resized.append(image)
                continue
            scale = target_width / image.size[0]
            resized.append(image.resize((target_width, int(image.size[1] * scale))))
        width = target_width + padding * 2
        height = sum(image.size[1] for image in resized) + gap * (len(resized) - 1) + padding * 2
        canvas = Image.new("RGB", (width, height), background)
        y = padding
        for image in resized:
            canvas.paste(image, (padding, y))
            y += image.size[1] + gap
        return canvas

    target_height = max(image.size[1] for image in images)
    resized = []
    for image in images:
        if image.size[1] == target_height:
            resized.append(image)
            continue
        scale = target_height / image.size[1]
        resized.append(image.resize((int(image.size[0] * scale), target_height)))
    width = sum(image.size[0] for image in resized) + gap * (len(resized) - 1) + padding * 2
    height = target_height + padding * 2
    canvas = Image.new("RGB", (width, height), background)
    x = padding
    for image in resized:
        canvas.paste(image, (x, padding))
        x += image.size[0] + gap
    return canvas


def _extract_labeled_table_body(source: Path, label: str) -> str:
    text = source.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"(?<!\\)%.*", "", text)
    pattern = re.compile(r"\\begin\{table\*?\}(?:\[[^\]]*\])?(?P<body>.*?)\\end\{table\*?\}", re.DOTALL)
    for match in pattern.finditer(text):
        block = match.group(0)
        if f"\\label{{{label}}}" not in block:
            continue
        body = match.group("body")
        body = _strip_latex_command(body, "caption")
        body = _strip_latex_command(body, "label")
        return body.strip()
    raise ValueError(f"Could not find table with label {label} in {source}")


def _filter_tabular_rows(table_body: str, keep_rows_matching: list[str] | None = None) -> str:
    if not keep_rows_matching:
        return table_body

    pattern = re.compile(r"\\begin\{tabular\}(?P<spec>\{.*?\})(?P<body>.*?)\\end\{tabular\}", re.DOTALL)
    match = pattern.search(table_body)
    if not match:
        return table_body

    tabular_body = match.group("body")
    keep_tokens = [token.strip() for token in keep_rows_matching if token and token.strip()]
    if not keep_tokens:
        return table_body

    def iter_chunks(text: str) -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = []
        buffer: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if buffer:
                buffer.append(line)
                if stripped.endswith("\\\\"):
                    chunks.append(("row", "\n".join(buffer)))
                    buffer = []
                continue

            if not stripped:
                chunks.append(("other", line))
                continue
            if stripped.startswith(("\\toprule", "\\midrule", "\\bottomrule", "\\cmidrule")):
                chunks.append(("rule", line))
                continue
            if "&" in stripped:
                buffer = [line]
                if stripped.endswith("\\\\"):
                    chunks.append(("row", "\n".join(buffer)))
                    buffer = []
                continue
            chunks.append(("other", line))
        if buffer:
            chunks.append(("row", "\n".join(buffer)))
        return chunks

    chunks = iter_chunks(tabular_body)
    filtered_chunks: list[str] = []
    body_started = False
    pending_rule: str | None = None
    bottomrule_line: str | None = None

    for kind, chunk in chunks:
        stripped = chunk.strip()
        if not body_started:
            filtered_chunks.append(chunk)
            if kind == "rule" and stripped.startswith("\\midrule"):
                body_started = True
            continue

        if kind == "rule":
            if stripped.startswith("\\bottomrule"):
                bottomrule_line = chunk
            elif stripped.startswith(("\\midrule", "\\cmidrule")):
                pending_rule = chunk
            continue

        if kind == "row":
            normalized_chunk = " ".join(line.strip() for line in chunk.splitlines())
            if any(token in normalized_chunk for token in keep_tokens):
                if pending_rule:
                    filtered_chunks.append(pending_rule)
                    pending_rule = None
                filtered_chunks.append(chunk)
            continue

        # Preserve non-row content only in the header section. Table bodies in this
        # workflow do not rely on standalone content after the first \midrule.

    if bottomrule_line:
        filtered_chunks.append(bottomrule_line)

    filtered_tabular = "\n".join(filtered_chunks)
    return table_body[: match.start("body")] + filtered_tabular + table_body[match.end("body") :]


def _render_latex_table(
    manifest: PaperManifest,
    source: Path,
    label: str,
    dpi: int = 220,
    keep_rows_matching: list[str] | None = None,
) -> Image.Image:
    source_root = Path(manifest.source_dir)
    main_tex = source_root / manifest.main_tex
    main_text = main_tex.read_text(encoding="utf-8", errors="ignore")
    preamble, _, _ = main_text.partition("\\begin{document}")
    minimal_preamble = "\n".join(
        [
            "\\documentclass{article}",
            "\\usepackage[margin=0.25in]{geometry}",
            "\\usepackage{booktabs}",
            "\\usepackage{graphicx}",
            "\\usepackage{array}",
            "\\usepackage{multirow}",
            "\\usepackage[table]{xcolor}",
            "\\usepackage{amsmath}",
            "\\usepackage{amssymb}",
            "\\pagestyle{empty}",
            "\\renewcommand{\\arraystretch}{1.1}",
        ]
    )
    table_body = _extract_labeled_table_body(source, label)
    table_body = _filter_tabular_rows(table_body, keep_rows_matching=keep_rows_matching)

    def _compile_table_document(tmpdir_path: Path, document_preamble: str) -> None:
        tex_path = tmpdir_path / "table_asset.tex"
        tex_path.write_text(
            document_preamble
            + "\n\\begin{document}\n\\thispagestyle{empty}\n\\pagestyle{empty}\n"
            + table_body
            + "\n\\end{document}\n",
            encoding="utf-8",
        )
        latexmk = shutil.which("latexmk")
        if latexmk:
            subprocess.run(
                [
                    latexmk,
                    "-pdf",
                    f"-outdir={tmpdir_path}",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    tex_path.relative_to(source_root).as_posix(),
                ],
                cwd=source_root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        pdflatex = shutil.which("pdflatex")
        if not pdflatex:
            raise RuntimeError("latexmk or pdflatex is required to render LaTeX table assets")
        subprocess.run(
            [
                pdflatex,
                f"-output-directory={tmpdir_path}",
                "-interaction=nonstopmode",
                "-halt-on-error",
                tex_path.relative_to(source_root).as_posix(),
            ],
            cwd=source_root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    with tempfile.TemporaryDirectory(prefix="paperpage-latex-", dir=source_root) as tmpdir:
        tmpdir_path = Path(tmpdir)
        try:
            _compile_table_document(tmpdir_path, preamble)
        except subprocess.CalledProcessError:
            _compile_table_document(tmpdir_path, minimal_preamble)
        image = _render_pdf_page(tmpdir_path / "table_asset.pdf", page=1, dpi=dpi)
    return _trim_whitespace(image)


def _copy_configured_assets(
    manifest: PaperManifest,
    resolved: dict,
    docs_dir: Path,
    project_config_dir: str | None = None,
    user_config_dir: str | None = None,
) -> tuple[dict[str, str], set[str]]:
    source_root = Path(manifest.source_dir)
    copied_links: dict[str, str] = {}
    copied_assets: set[str] = set()

    for item in resolved.get("assets", {}).get("copies", []):
        source_value = item.get("source")
        dest_value = item.get("dest")
        if not source_value or not dest_value:
            continue

        src = _resolve_source_path(
            source_value,
            source_root,
            project_config_dir=project_config_dir,
            user_config_dir=user_config_dir,
        )
        if not src.is_file():
            continue

        dest_rel = Path(dest_value)
        dest = docs_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

        link_key = item.get("link_key")
        if link_key:
            copied_links[link_key] = dest_rel.as_posix()
        copied_assets.add(dest_rel.as_posix())

    for item in resolved.get("assets", {}).get("composites", []):
        source_values = item.get("sources") or []
        dest_value = item.get("dest")
        if not source_values or not dest_value:
            continue

        sources = [
            _resolve_source_path(
                source_value,
                source_root,
                project_config_dir=project_config_dir,
                user_config_dir=user_config_dir,
            )
            for source_value in source_values
        ]
        if not all(source.is_file() for source in sources):
            continue

        composite = _compose_images(
            sources,
            layout=str(item.get("layout", "row")).lower(),
            gap=int(item.get("gap", 16)),
            padding=int(item.get("padding", 16)),
            background=str(item.get("background", "white")),
        )

        dest_rel = Path(dest_value)
        dest = docs_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        composite.save(dest)

        link_key = item.get("link_key")
        if link_key:
            copied_links[link_key] = dest_rel.as_posix()
        copied_assets.add(dest_rel.as_posix())

    for item in resolved.get("assets", {}).get("crops", []):
        source_value = item.get("source")
        dest_value = item.get("dest")
        box = item.get("box")
        if not source_value or not dest_value or not box:
            continue

        src = _resolve_source_path(
            source_value,
            source_root,
            project_config_dir=project_config_dir,
            user_config_dir=user_config_dir,
        )
        if not src.is_file():
            continue

        unit = str(item.get("unit", "fraction")).lower()
        dpi = int(item.get("dpi", 220))
        autotrim = bool(item.get("autotrim", True))

        if src.suffix.lower() == ".pdf":
            page = int(item.get("page", 1))
            image = _render_pdf_page(src, page=page, dpi=dpi)
        else:
            image = Image.open(src).convert("RGB")

        crop = image.crop(_box_to_pixels(box, image, unit))
        if autotrim:
            crop = _trim_whitespace(crop)

        dest_rel = Path(dest_value)
        dest = docs_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dest)

        link_key = item.get("link_key")
        if link_key:
            copied_links[link_key] = dest_rel.as_posix()
        copied_assets.add(dest_rel.as_posix())

    for item in resolved.get("assets", {}).get("latex_tables", []):
        source_value = item.get("source")
        label = item.get("label")
        dest_value = item.get("dest")
        if not source_value or not label or not dest_value:
            continue

        src = _resolve_source_path(
            source_value,
            source_root,
            project_config_dir=project_config_dir,
            user_config_dir=user_config_dir,
        )
        if not src.is_file():
            continue

        image = _render_latex_table(
            manifest,
            src,
            label=str(label),
            dpi=int(item.get("dpi", 220)),
            keep_rows_matching=item.get("keep_rows_matching"),
        )

        dest_rel = Path(dest_value)
        dest = docs_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest)

        link_key = item.get("link_key")
        if link_key:
            copied_links[link_key] = dest_rel.as_posix()
        copied_assets.add(dest_rel.as_posix())

    return copied_links, copied_assets


def _slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "paper"


def _format_bibtex_authors(authors: list[str]) -> str:
    if not authors:
        return "Author"
    return " and ".join(authors)


def _build_generated_bibtex(manifest: PaperManifest) -> str:
    key = f"{manifest.authors[0].split()[-1].lower() if manifest.authors else 'paper'}{manifest.year or '2026'}{_slugify_title(manifest.title).split('-')[0]}"
    entry_type = "inproceedings" if manifest.venue else "article"
    lines = [
        f"@{entry_type}{{{key},",
        "  title={" + manifest.title + "},",
        "  author={" + _format_bibtex_authors(manifest.authors) + "},",
    ]
    if manifest.venue:
        lines.append("  booktitle={" + manifest.venue + "},")
    if manifest.year:
        lines.append("  year={" + manifest.year + "},")
    lines.append("}")
    return "\n".join(lines)


def _prune_unused_copied_assets(
    copied_assets: list[str],
    story_blocks: list[dict],
    docs_dir: Path,
    hero_asset: str | None = None,
) -> list[str]:
    if not copied_assets:
        return copied_assets

    used_assets = {hero_asset} if hero_asset else set()
    for block in story_blocks:
        for asset_image in block.get("asset_images", []) or []:
            used_assets.add(asset_image)
        asset_image = block.get("asset_image")
        if asset_image:
            used_assets.add(asset_image)

    for rel in copied_assets:
        if rel in used_assets:
            continue
        path = docs_dir / rel
        if path.is_file():
            path.unlink()

    return [rel for rel in copied_assets if rel in used_assets]


def _render_template(template_name: str, context: dict) -> str:
    template_root = resources.files("paperpage").joinpath("templates")
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(f"{template_name}/index.html.j2")
    return template.render(**context)


def _is_local_asset_url(url: str | None) -> bool:
    if not url:
        return False
    return not re.match(r"^(?:[a-z]+:)?//|^[a-z]+:|^#", url, re.IGNORECASE)


def _fingerprint_path(path: Path) -> str:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    return digest[:10]


def _detail_image_paths(details: dict | None) -> list[str]:
    if not isinstance(details, dict):
        return []
    paths: list[str] = []
    for item in details.get("items", []) or []:
        image = item.get("image")
        if image:
            paths.append(str(image))
    return paths


def _build_asset_url_map(
    docs_dir: Path,
    copied_assets: list[str],
    resolved: dict | None = None,
    story_blocks: list[dict] | None = None,
) -> dict[str, str]:
    asset_urls: dict[str, str] = {}
    candidate_paths = set(copied_assets)
    candidate_paths.update({"static/index.css", "static/index.js"})

    for url in ((resolved or {}).get("links", {}) or {}).values():
        if _is_local_asset_url(url):
            candidate_paths.add(url)

    candidate_paths.update(_detail_image_paths(((resolved or {}).get("hero", {}) or {}).get("details")))
    for block in story_blocks or []:
        candidate_paths.update(_detail_image_paths(block.get("details")))

    for rel in candidate_paths:
        path = docs_dir / rel
        if not path.is_file():
            continue
        asset_urls[rel] = f"{rel}?v={_fingerprint_path(path)}"
    return asset_urls


def build_project_draft(manifest: PaperManifest, editorial_context: dict, out_dir: str | Path) -> BuildArtifacts:
    out_root = Path(out_dir).resolve()
    docs_dir = out_root / "docs"
    build_dir = out_root / "build"
    docs_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    resolved = editorial_context["resolved"]
    theme_name = resolved.get("theme", "academic-project-page")
    _copy_theme_assets(theme_name, docs_dir)
    copied_link_overrides, configured_assets = _copy_configured_assets(
        manifest,
        resolved,
        docs_dir,
        project_config_dir=editorial_context.get("project_config_dir"),
        user_config_dir=editorial_context.get("user_config_dir"),
    )
    selected_assets = _select_gallery_assets(manifest, resolved, configured_assets)
    copied_assets = _copy_selected_assets(manifest, selected_assets, docs_dir, configured_assets)
    show_hero_figure = bool(resolved.get("hero", {}).get("show_figure", True))
    hero_asset = copied_assets[0] if show_hero_figure and copied_assets else None
    story_blocks = _build_story_blocks(manifest, resolved, copied_assets, hero_asset=hero_asset)
    copied_assets = _prune_unused_copied_assets(copied_assets, story_blocks, docs_dir, hero_asset=hero_asset)

    if copied_link_overrides:
        resolved.setdefault("links", {})
        resolved["links"].update(copied_link_overrides)

    manifest_path = build_dir / "manifest.yml"
    manifest_path.write_text(yaml.safe_dump(manifest.to_dict(), sort_keys=False), encoding="utf-8")

    context_payload = {
        **editorial_context,
        "selected_assets": copied_assets,
        "story_blocks": story_blocks,
    }
    editorial_context_path = build_dir / "editorial_context.yml"
    editorial_context_path.write_text(yaml.safe_dump(context_payload, sort_keys=False), encoding="utf-8")

    configured_bibtex = resolved.get("citation", {}).get("bibtex")
    template_context = {
        "manifest": manifest.to_dict(),
        "page": resolved,
        "selected_assets": copied_assets,
        "hero_asset": hero_asset,
        "story_blocks": story_blocks,
        "instruction_stack": editorial_context["instruction_stack"],
        "generated_bibtex": configured_bibtex or _build_generated_bibtex(manifest),
        "asset_urls": _build_asset_url_map(docs_dir, copied_assets, resolved, story_blocks),
    }
    html = _render_template(theme_name, template_context)
    index_path = docs_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    return BuildArtifacts(
        out_dir=out_root,
        docs_dir=docs_dir,
        build_dir=build_dir,
        manifest_path=manifest_path,
        editorial_context_path=editorial_context_path,
        index_path=index_path,
    )
