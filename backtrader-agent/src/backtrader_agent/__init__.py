"""Independent deterministic runtime for the Backtrader authoring agent."""

from .contracts import DatasetManifest, StrategySpec
from .errors import AgentError

__all__ = ["AgentError", "DatasetManifest", "StrategySpec"]
__version__ = "0.1.0"
