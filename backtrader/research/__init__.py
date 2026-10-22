"""Native Backtrader factor-research APIs.

Importing this package keeps pandas and fincore lazy; their runtime checks are
performed when a ResearchSpec or ResearchDataset is constructed.
"""

from .dataset import ResearchDataset
from ..errors import (
    DataQualityError,
    DatasetError,
    DependencyError,
    FactorComputationContext,
    FactorComputationError,
    ResearchConfigError,
    ResearchError,
)

from .factor_indicator import FactorIndicator
from .factor_report import write_factor_report
from .factor_strategy import FactorStrategy
from .inputs import AlignedBars, AlignedPITInput, prealign_bars, prealign_pit_table
from .specs import FactorSpec, ResearchSpec
from .storage import load_dataset
from .fincore_adapter import evaluate_dataset

ConfigError = ResearchConfigError

__all__ = (
    "AlignedBars",
    "AlignedPITInput",
    "ConfigError",
    "ResearchConfigError",
    "DataQualityError",
    "DatasetError",
    "DependencyError",
    "FactorComputationContext",
    "FactorComputationError",
    "FactorIndicator",
    "FactorSpec",
    "FactorStrategy",
    "ResearchDataset",
    "ResearchError",
    "ResearchSpec",
    "evaluate_dataset",
    "load_dataset",
    "prealign_bars",
    "prealign_pit_table",
    "write_factor_report",
)
