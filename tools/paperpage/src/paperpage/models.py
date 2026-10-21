from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PaperSection:
    title: str
    source: str
    summary: str = ""


@dataclass
class PaperAsset:
    path: str
    source: str
    kind: str = "figure"
    score: int = 0
    caption: str = ""
    section_title: str = ""


@dataclass
class PaperAuthor:
    name: str
    affiliations: list[str] = field(default_factory=list)
    affiliation_indices: list[int] = field(default_factory=list)


@dataclass
class PaperManifest:
    paper_path: str
    source_dir: str
    main_tex: str
    title: str
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    author_entries: list[PaperAuthor] = field(default_factory=list)
    abstract: str = ""
    summary: str = ""
    venue: str = ""
    year: str = ""
    section_inputs: list[str] = field(default_factory=list)
    sections: list[PaperSection] = field(default_factory=list)
    figure_assets: list[PaperAsset] = field(default_factory=list)
    table_assets: list[PaperAsset] = field(default_factory=list)
    bibliography_files: list[str] = field(default_factory=list)
    candidate_hero_assets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BuildArtifacts:
    out_dir: Path
    docs_dir: Path
    build_dir: Path
    manifest_path: Path
    editorial_context_path: Path
    index_path: Path


@dataclass
class DemoMedia:
    type: str
    src: str
    alt: str = ""
    caption: str = ""


@dataclass
class DemoChoice:
    value: str
    text: str
    label: str = ""


@dataclass
class DemoAnswer:
    canonical: str = ""
    aliases: list[str] = field(default_factory=list)
    explanation: str = ""
    variants: list["DemoAnswerVariant"] = field(default_factory=list)


@dataclass
class DemoAnswerVariant:
    label: str
    answer: str
    explanation: str = ""


@dataclass
class DemoPrediction:
    model: str
    answer: str = ""
    correct: bool | None = None
    explanation: str = ""
    variants: list["DemoPredictionVariant"] = field(default_factory=list)


@dataclass
class DemoPredictionVariant:
    label: str
    answer: str
    correct: bool | None = None
    explanation: str = ""


@dataclass
class DemoExample:
    id: str
    prompt: str
    title: str = ""
    task: str = ""
    mode: str = "image_qa"
    media: list[DemoMedia] = field(default_factory=list)
    choices: list[DemoChoice] = field(default_factory=list)
    answer: DemoAnswer | None = None
    predictions: list[DemoPrediction] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class DemoManifest:
    source_path: str
    title: str = ""
    subtitle: str = ""
    intro: str = ""
    mode: str = "image_qa"
    summary: dict = field(default_factory=dict)
    examples: list[DemoExample] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DemoBuildArtifacts:
    out_dir: Path
    docs_dir: Path
    build_dir: Path
    demo_dir: Path
    manifest_path: Path
    editorial_context_path: Path
    index_path: Path
    examples_json_path: Path
    summary_json_path: Path | None = None
