from __future__ import annotations

from dataclasses import asdict
import json
from importlib import resources
from pathlib import Path
import hashlib
import re
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape
import yaml

from .models import (
    DemoAnswer,
    DemoAnswerVariant,
    DemoBuildArtifacts,
    DemoChoice,
    DemoExample,
    DemoManifest,
    DemoMedia,
    DemoPrediction,
    DemoPredictionVariant,
)


def _read_demo_source(path: Path) -> dict:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".jsonl":
        examples = [json.loads(line) for line in text.splitlines() if line.strip()]
        return {"examples": examples}
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return {"examples": payload}
        return payload
    if suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text) or {}
        if isinstance(payload, list):
            return {"examples": payload}
        return payload
    raise ValueError(f"Unsupported demo source format: {path}")


def _load_demo_summary(source_path: Path, payload: dict) -> dict:
    embedded = payload.get("summary")
    if isinstance(embedded, dict):
        return embedded

    summary_path = source_path.with_name("summary.json")
    if summary_path.is_file():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {}


def _normalize_text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip() or fallback


def _normalize_media(items: list[dict] | None) -> list[DemoMedia]:
    media_items: list[DemoMedia] = []
    for item in items or []:
        src = _normalize_text(item.get("src"))
        if not src:
            continue
        media_items.append(
            DemoMedia(
                type=_normalize_text(item.get("type"), "image"),
                src=src,
                alt=_normalize_text(item.get("alt")),
                caption=_normalize_text(item.get("caption")),
            )
        )
    return media_items


def _normalize_choices(items: list[dict] | None) -> list[DemoChoice]:
    choices: list[DemoChoice] = []
    for item in items or []:
        value = _normalize_text(item.get("value"))
        text = _normalize_text(item.get("text"), value)
        if not value and not text:
            continue
        choices.append(
            DemoChoice(
                value=value or text,
                text=text or value,
                label=_normalize_text(item.get("label")),
            )
        )
    return choices


def _normalize_answer(item: dict | None) -> DemoAnswer | None:
    if not item:
        return None
    canonical = _normalize_text(item.get("canonical"))
    variants = _normalize_answer_variants(item.get("variants"))
    if not canonical and not variants:
        return None
    aliases = [str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()]
    return DemoAnswer(
        canonical=canonical,
        aliases=aliases,
        explanation=_normalize_text(item.get("explanation")),
        variants=variants,
    )


def _normalize_predictions(items: list[dict] | None) -> list[DemoPrediction]:
    predictions: list[DemoPrediction] = []
    for item in items or []:
        model = _normalize_text(item.get("model"))
        answer = _normalize_text(item.get("answer"))
        variants = _normalize_prediction_variants(item.get("variants"))
        if not model and not answer and not variants:
            continue
        predictions.append(
            DemoPrediction(
                model=model or "Model",
                answer=answer,
                correct=item.get("correct"),
                explanation=_normalize_text(item.get("explanation")),
                variants=variants,
            )
        )
    return predictions


def _normalize_answer_variants(items: list[dict] | None) -> list[DemoAnswerVariant]:
    variants: list[DemoAnswerVariant] = []
    for item in items or []:
        label = _normalize_text(item.get("label"))
        answer = _normalize_text(item.get("answer"))
        if not label and not answer:
            continue
        variants.append(
            DemoAnswerVariant(
                label=label or "Answer",
                answer=answer,
                explanation=_normalize_text(item.get("explanation")),
            )
        )
    return variants


def _normalize_prediction_variants(items: list[dict] | None) -> list[DemoPredictionVariant]:
    variants: list[DemoPredictionVariant] = []
    for item in items or []:
        label = _normalize_text(item.get("label"))
        answer = _normalize_text(item.get("answer"))
        if not label and not answer:
            continue
        variants.append(
            DemoPredictionVariant(
                label=label or "Variant",
                answer=answer,
                correct=item.get("correct"),
                explanation=_normalize_text(item.get("explanation")),
            )
        )
    return variants


def load_demo_manifest(examples_path: str | Path) -> DemoManifest:
    source_path = Path(examples_path).resolve()
    payload = _read_demo_source(source_path)
    summary = _load_demo_summary(source_path, payload)
    examples: list[DemoExample] = []
    default_mode = _normalize_text(payload.get("mode"), "image_qa")
    for index, item in enumerate(payload.get("examples") or []):
        prompt = _normalize_text(item.get("prompt"))
        if not prompt:
            continue
        example_id = _normalize_text(item.get("id"), f"example-{index + 1}")
        title = _normalize_text(item.get("title"), _normalize_text(item.get("task"), f"Example {index + 1}"))
        examples.append(
            DemoExample(
                id=example_id,
                prompt=prompt,
                title=title,
                task=_normalize_text(item.get("task")),
                mode=_normalize_text(item.get("mode"), default_mode),
                media=_normalize_media(item.get("media")),
                choices=_normalize_choices(item.get("choices")),
                answer=_normalize_answer(item.get("answer")),
                predictions=_normalize_predictions(item.get("predictions")),
                meta=item.get("meta") or {},
            )
        )

    return DemoManifest(
        source_path=str(source_path),
        title=_normalize_text(payload.get("title")),
        subtitle=_normalize_text(payload.get("subtitle")),
        intro=_normalize_text(payload.get("intro")),
        mode=default_mode,
        summary=summary,
        examples=examples,
    )


def _render_demo_template(template_name: str, context: dict) -> str:
    template_root = resources.files("paperpage").joinpath("templates")
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(f"{template_name}/index.html.j2")
    return template.render(**context)


def _copy_demo_theme_assets(theme_name: str, docs_dir: Path) -> None:
    static_root = resources.files("paperpage").joinpath(f"templates/{theme_name}/static")
    target_dir = docs_dir / "static"
    target_dir.mkdir(parents=True, exist_ok=True)
    for asset in static_root.iterdir():
        if asset.is_file():
            shutil.copy2(asset, target_dir / asset.name)


def _fingerprint_path(path: Path) -> str:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    return digest[:10]


def _is_remote_url(value: str) -> bool:
    return bool(re.match(r"^(?:[a-z]+:)?//|^[a-z]+:", value, re.IGNORECASE))


def _copy_demo_media(manifest: DemoManifest, docs_dir: Path) -> DemoManifest:
    copied_examples: list[DemoExample] = []
    source_root = Path(manifest.source_path).resolve().parent
    media_root = docs_dir / "assets" / "demo" / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    copied_by_source: dict[str, str] = {}

    for example in manifest.examples:
        copied_media: list[DemoMedia] = []
        for index, media in enumerate(example.media):
            if _is_remote_url(media.src):
                copied_media.append(media)
                continue
            src = (source_root / media.src).resolve()
            if not src.is_file():
                continue
            src_key = str(src)
            rel_url = copied_by_source.get(src_key)
            if rel_url is None:
                digest = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
                safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", src.stem).strip("-") or "media"
                dest_name = f"{safe_stem}-{digest}{src.suffix.lower()}"
                dest = media_root / dest_name
                if not dest.exists():
                    shutil.copy2(src, dest)
                rel = Path("..") / "assets" / "demo" / "media" / dest_name
                rel_url = f"{rel.as_posix()}?v={_fingerprint_path(dest)}"
                copied_by_source[src_key] = rel_url
            copied_media.append(
                DemoMedia(
                    type=media.type,
                    src=rel_url,
                    alt=media.alt,
                    caption=media.caption,
                )
            )
        copied_examples.append(
            DemoExample(
                id=example.id,
                prompt=example.prompt,
                title=example.title,
                task=example.task,
                mode=example.mode,
                media=copied_media,
                choices=example.choices,
                answer=example.answer,
                predictions=example.predictions,
                meta=example.meta,
            )
        )

    return DemoManifest(
        source_path=manifest.source_path,
        title=manifest.title,
        subtitle=manifest.subtitle,
        intro=manifest.intro,
        mode=manifest.mode,
        summary=manifest.summary,
        examples=copied_examples,
    )


def _derive_available_models(manifest: DemoManifest) -> list[str]:
    names = []
    seen = set()
    for example in manifest.examples:
        for prediction in example.predictions:
            model = _normalize_text(prediction.model)
            if model and model not in seen:
                seen.add(model)
                names.append(model)
        compare_groups = example.meta.get("compare_groups") if isinstance(example.meta, dict) else None
        if isinstance(compare_groups, list):
            for group in compare_groups:
                if not isinstance(group, dict):
                    continue
                for prediction in group.get("predictions") or []:
                    if not isinstance(prediction, dict):
                        continue
                    model = _normalize_text(prediction.get("model"))
                    if model and model not in seen:
                        seen.add(model)
                        names.append(model)
    return names


def build_demo_draft(examples_path: str | Path, editorial_context: dict, out_dir: str | Path) -> DemoBuildArtifacts:
    out_root = Path(out_dir).resolve()
    docs_dir = out_root / "docs"
    build_dir = out_root / "build"
    demo_dir = docs_dir / "demo"
    docs_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    demo_dir.mkdir(parents=True, exist_ok=True)

    resolved = editorial_context["resolved"]
    demo_config = resolved.get("demo", {}) or {}
    theme_name = demo_config.get("theme", "demo-basic")

    _copy_demo_theme_assets(theme_name, docs_dir)
    manifest = load_demo_manifest(examples_path)
    manifest = _copy_demo_media(manifest, docs_dir)
    available_models = manifest.summary.get("models") or _derive_available_models(manifest)
    default_compare_models = manifest.summary.get("default_compare_models") or available_models[:2]

    title = _normalize_text(demo_config.get("title"), manifest.title or "Interactive Demo")
    subtitle = _normalize_text(demo_config.get("subtitle"), manifest.subtitle)
    intro = _normalize_text(
        demo_config.get("intro"),
        manifest.intro or "Try a random example, submit your answer, and compare it with the cached model response.",
    )
    back_link = {
        "label": _normalize_text(demo_config.get("back_link_label"), "Back to project page"),
        "href": _normalize_text(demo_config.get("back_link_href"), "../"),
    }
    enabled_modes = demo_config.get("modes") or ["compare", "quiz"]
    enabled_modes = [str(mode).strip() for mode in enabled_modes if str(mode).strip()]
    if not enabled_modes:
        enabled_modes = ["compare"]
    default_mode = _normalize_text(demo_config.get("default_mode"), enabled_modes[0] if enabled_modes else "compare")
    if default_mode not in enabled_modes:
        default_mode = enabled_modes[0]
    quiz_reveal_model = _normalize_text(
        demo_config.get("quiz_reveal_model"),
        (default_compare_models[0] if default_compare_models else (available_models[0] if available_models else "")),
    )

    manifest_path = build_dir / "demo_manifest.yml"
    manifest_path.write_text(yaml.safe_dump(manifest.to_dict(), sort_keys=False), encoding="utf-8")

    context_payload = {
        **editorial_context,
        "demo": {
            "theme": theme_name,
            "title": title,
            "subtitle": subtitle,
            "intro": intro,
            "back_link": back_link,
            "show_model_predictions": bool(demo_config.get("show_model_predictions", True)),
            "show_compare_model_selector": bool(demo_config.get("show_compare_model_selector", True)),
            "show_summary_breakdown": bool(demo_config.get("show_summary_breakdown", True)),
            "modes": enabled_modes,
            "default_mode": default_mode,
            "available_models": available_models,
            "default_compare_models": default_compare_models,
            "quiz_reveal_model": quiz_reveal_model,
        },
    }
    editorial_context_path = build_dir / "demo_context.yml"
    editorial_context_path.write_text(yaml.safe_dump(context_payload, sort_keys=False), encoding="utf-8")

    examples_json_path = docs_dir / "assets" / "demo" / "examples.json"
    examples_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path = docs_dir / "assets" / "demo" / "summary.json"
    summary_json_path.write_text(json.dumps(manifest.summary, indent=2), encoding="utf-8")
    examples_json_path.write_text(
        json.dumps(
            {
                "examples": [asdict(example) for example in manifest.examples],
                "summary": manifest.summary,
                "available_models": available_models,
                "default_compare_models": default_compare_models,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    examples_json_url = f"../assets/demo/examples.json?v={_fingerprint_path(examples_json_path)}"
    static_urls = {}
    for rel in ("static/demo.css", "static/demo.js"):
        path = docs_dir / rel
        if path.is_file():
            static_urls[rel] = f"../{rel}?v={_fingerprint_path(path)}"

    html = _render_demo_template(
        theme_name,
        {
            "demo": {
                "title": title,
                "subtitle": subtitle,
                "intro": intro,
                "back_link": back_link,
                "show_model_predictions": bool(demo_config.get("show_model_predictions", True)),
                "show_compare_model_selector": bool(demo_config.get("show_compare_model_selector", True)),
                "show_summary_breakdown": bool(demo_config.get("show_summary_breakdown", True)),
                "modes": enabled_modes,
                "default_mode": default_mode,
                "available_models": available_models,
                "default_compare_models": default_compare_models,
                "quiz_reveal_model": quiz_reveal_model,
            },
            "examples_json_url": examples_json_url,
            "static_urls": static_urls,
        },
    )
    index_path = demo_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    return DemoBuildArtifacts(
        out_dir=out_root,
        docs_dir=docs_dir,
        build_dir=build_dir,
        demo_dir=demo_dir,
        manifest_path=manifest_path,
        editorial_context_path=editorial_context_path,
        index_path=index_path,
        examples_json_path=examples_json_path,
        summary_json_path=summary_json_path,
    )
