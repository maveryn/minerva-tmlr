from __future__ import annotations

import argparse
from pathlib import Path

from .config import build_editorial_context
from .demo import build_demo_draft
from .extract import extract_paper_bundle
from .render import build_project_draft


def _read_instruction_text(inline_text: str | None, file_path: str | None) -> str | None:
    parts = []
    if file_path:
        parts.append(Path(file_path).read_text(encoding="utf-8").strip())
    if inline_text:
        parts.append(inline_text.strip())
    merged = "\n\n".join(part for part in parts if part)
    return merged or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a project-page draft from a LaTeX paper bundle.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Extract and render a project-page draft.")
    init_parser.add_argument("--paper", required=True, help="Path to a LaTeX paper directory or arXiv zip.")
    init_parser.add_argument("--out", required=True, help="Output directory for build and docs artifacts.")
    init_parser.add_argument("--main-tex", default=None, help="Optional explicit main TeX file relative to the paper root.")
    init_parser.add_argument("--project-config", default=None, help="Optional YAML file with project-specific defaults.")
    init_parser.add_argument("--user-config", default=None, help="Optional YAML file with user overrides.")
    init_parser.add_argument("--instructions", default=None, help="Additional user instructions with highest priority.")
    init_parser.add_argument("--instructions-file", default=None, help="Path to a text file of user instructions.")
    init_parser.add_argument("--theme", default=None, help="Template/theme name to use.")

    demo_parser = subparsers.add_parser("demo", help="Build a static interactive demo from normalized examples.")
    demo_parser.add_argument("--examples", required=True, help="Path to a normalized demo JSON, JSONL, or YAML file.")
    demo_parser.add_argument("--out", required=True, help="Output directory for build and docs artifacts.")
    demo_parser.add_argument("--project-config", default=None, help="Optional YAML file with project-specific defaults.")
    demo_parser.add_argument("--user-config", default=None, help="Optional YAML file with user overrides.")
    demo_parser.add_argument("--instructions", default=None, help="Additional user instructions with highest priority.")
    demo_parser.add_argument("--instructions-file", default=None, help="Path to a text file of user instructions.")

    args = parser.parse_args()

    if args.command == "init":
        user_instructions = _read_instruction_text(args.instructions, args.instructions_file)
        manifest = extract_paper_bundle(args.paper, main_tex=args.main_tex)
        editorial_context = build_editorial_context(
            project_config_path=args.project_config,
            user_config_path=args.user_config,
            user_instructions=user_instructions,
            theme=args.theme,
        )
        artifacts = build_project_draft(manifest, editorial_context, args.out)
        print(f"Wrote manifest to {artifacts.manifest_path}")
        print(f"Wrote editorial context to {artifacts.editorial_context_path}")
        print(f"Wrote page draft to {artifacts.index_path}")
    elif args.command == "demo":
        user_instructions = _read_instruction_text(args.instructions, args.instructions_file)
        editorial_context = build_editorial_context(
            project_config_path=args.project_config,
            user_config_path=args.user_config,
            user_instructions=user_instructions,
        )
        artifacts = build_demo_draft(args.examples, editorial_context, args.out)
        print(f"Wrote demo manifest to {artifacts.manifest_path}")
        print(f"Wrote demo context to {artifacts.editorial_context_path}")
        print(f"Wrote demo page to {artifacts.index_path}")


if __name__ == "__main__":
    main()
