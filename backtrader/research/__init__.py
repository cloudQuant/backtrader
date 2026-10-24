"""Native Backtrader factor-research APIs.

Importing this package keeps pandas and fincore lazy; their runtime checks are
performed when a research spec, panel or evaluation is constructed.
"""

from ..errors import (
    DataQualityError,
    DatasetError,
    DependencyError,
    FactorComputationContext,
    FactorComputationError,
    ResearchConfigError,
    ResearchError,
)
from .align import AlignedFeed, align_to_grid, feed_alignment
from .factor_indicator import FactorIndicator
from .factor_report import write_factor_report
from .factor_strategy import FactorStrategy
from .fincore_adapter import evaluate_frames
from .live import (
    LiveFactorInput,
    LiveFactorOutput,
    LiveFactorOutputStatus,
    LiveFactorPlan,
    LiveFactorReadiness,
    LiveFactorResult,
    LiveFactorSet,
    LiveFactorSnapshot,
)
from .panel import FactorPanel
from .sink import CsvSink, FactorSink, MemorySink, PanelContext
from .specs import FactorSpec, ResearchSpec

ConfigError = ResearchConfigError

__all__ = (
    "AlignedFeed",
    "ConfigError",
    "CsvSink",
    "DataQualityError",
    "DatasetError",
    "DependencyError",
    "FactorComputationContext",
    "FactorComputationError",
    "FactorIndicator",
    "FactorPanel",
    "FactorSink",
    "FactorSpec",
    "FactorStrategy",
    "LiveFactorInput",
    "LiveFactorOutput",
    "LiveFactorOutputStatus",
    "LiveFactorPlan",
    "LiveFactorReadiness",
    "LiveFactorResult",
    "LiveFactorSet",
    "LiveFactorSnapshot",
    "MemorySink",
    "PanelContext",
    "ResearchConfigError",
    "ResearchError",
    "ResearchSpec",
    "align_to_grid",
    "evaluate_frames",
    "feed_alignment",
    "write_factor_report",
)
