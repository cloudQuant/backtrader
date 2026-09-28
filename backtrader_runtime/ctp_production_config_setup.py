"""Retired entry points for the legacy second CTP production config writer.

The ``ctp_production`` schema parser remains in :mod:`backtrader_runtime.config`
for migration and audit compatibility. Writing a separate production config is
retired: SimNow and any future production CTP mode share the registered
``examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`` file.

Both historical writer functions reject immediately. They intentionally do not
inspect source arguments, inspect a destination, read files, or create files.
"""

from __future__ import annotations

import os
from typing import NoReturn, Optional, Sequence, Tuple, Union

from .errors import CONFIG_SCHEMA_UNSUPPORTED, RuntimeConfigError


def _reject_retired_writer() -> NoReturn:
    raise RuntimeConfigError(
        CONFIG_SCHEMA_UNSUPPORTED,
        "SimNow and future production CTP modes share the canonical private "
        "config.yaml; the separate production-config writer is retired",
        field_path="runtime_dir",
        reason="separate_production_config_not_supported",
    )


def prepare_ctp_production_config_sources(
    sources: Sequence[Tuple[Union[os.PathLike, str], str]],
    *,
    runtime_dir: Optional[Union[os.PathLike, str]] = None,
) -> NoReturn:
    """Reject the retired multi-source second-config writer without I/O."""

    _reject_retired_writer()


def prepare_ctp_production_config(
    source_path: Union[os.PathLike, str],
    *,
    source_format: str,
    runtime_dir: Optional[Union[os.PathLike, str]] = None,
) -> NoReturn:
    """Reject the retired single-source second-config writer without I/O."""

    _reject_retired_writer()
