from __future__ import annotations

from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _read_yaml(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_default_editorial_config() -> dict[str, Any]:
    with resources.files("paperpage").joinpath("defaults/editorial.yml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build_editorial_context(
    project_config_path: str | Path | None = None,
    user_config_path: str | Path | None = None,
    user_instructions: str | None = None,
    theme: str | None = None,
) -> dict[str, Any]:
    defaults = load_default_editorial_config()
    project_config = _read_yaml(project_config_path)
    user_config = _read_yaml(user_config_path)
    project_config_dir = str(Path(project_config_path).resolve().parent) if project_config_path else None
    user_config_dir = str(Path(user_config_path).resolve().parent) if user_config_path else None

    resolved = deepcopy(defaults)
    resolved = _deep_merge(resolved, project_config)
    resolved = _deep_merge(resolved, user_config)

    if theme:
        resolved["theme"] = theme

    instruction_stack = []
    if user_instructions:
        instruction_stack.append({"source": "user", "text": user_instructions.strip()})

    user_text = user_config.get("instructions")
    if user_text:
        instruction_stack.append({"source": "user_config", "text": str(user_text).strip()})

    project_text = project_config.get("instructions")
    if project_text:
        instruction_stack.append({"source": "project_config", "text": str(project_text).strip()})

    default_text = defaults.get("instructions")
    if default_text:
        instruction_stack.append({"source": "defaults", "text": str(default_text).strip()})

    return {
        "resolved": resolved,
        "project_config_dir": project_config_dir,
        "user_config_dir": user_config_dir,
        "instruction_precedence": [
            "user",
            "user_config",
            "project_config",
            "defaults",
        ],
        "instruction_stack": instruction_stack,
    }
