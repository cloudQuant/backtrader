"""Runtime directory layout rooted in the selected Backtrader checkout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    target: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", self.target.resolve())

    @property
    def root(self) -> Path:
        return self.target / ".backtrader-skills"

    @property
    def data_roots(self) -> Path:
        return self.root / "data-roots.json"

    @property
    def datasets(self) -> Path:
        return self.root / "datasets"

    @property
    def dataset_objects(self) -> Path:
        return self.datasets / "objects"

    @property
    def dataset_manifests(self) -> Path:
        return self.datasets / "manifests"

    @property
    def drafts(self) -> Path:
        return self.root / "drafts"

    @property
    def tokens(self) -> Path:
        return self.root / "tokens"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def installs(self) -> Path:
        return self.root / "installs"

    def ensure(self) -> "RuntimePaths":
        for directory in (
            self.root,
            self.dataset_objects,
            self.dataset_manifests,
            self.drafts,
            self.tokens,
            self.runs,
            self.installs,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self
