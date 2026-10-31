"""Small configuration-first fences for retired direct trading entrypoints.

This module intentionally depends only on the Iteration 41 configuration
layer. A historical script can import it before Backtrader, a provider, or a
native CTP extension, so rejected invocations cannot reach an old direct
execution path while the migration is incomplete.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO, Union

from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError


def _write_error(error: RuntimeConfigError, output: TextIO) -> None:
    """Emit the same small redacted JSON shape used by the runtime CLI."""

    print(json.dumps(error.as_dict(), ensure_ascii=False, sort_keys=True), file=output)


def legacy_direct_execution_error(component: str) -> RuntimeConfigError:
    """Return the deterministic error used for a retained direct writer.

    ``component`` is deliberately not included in the public error payload:
    this avoids leaking a legacy parameter file, credential, or endpoint.
    """

    del component
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "the historical direct execution entrypoint is not supported by the Iteration 41 "
        "runtime; use the registered configuration-first migration route",
        field_path="legacy_entrypoint",
        reason="legacy_direct_execution_not_supported",
    )


def run_legacy_config_first_cli(
    runtime_dir: Union[str, Path],
    argv: Optional[Sequence[str]] = None,
    *,
    stderr: Optional[TextIO] = None,
) -> int:
    """Run a retired script only through its fixed registered runtime directory.

    Historical switches once selected providers, YAML files, dry-run behavior,
    or process-child modes. They are rejected before importing the legacy
    script body. A no-argument invocation is retained as a convenience alias
    for ``bt-runtime run --strategy-dir <runtime-dir>``; that still enforces a
    mandatory local ``config.yaml`` and exact code-owned registration.
    """

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        error = RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "legacy CLI arguments cannot select or override an Iteration 41 runtime; "
            "supplied values are redacted (***)",
            field_path="argv",
            reason="legacy_cli_arguments_not_supported",
        )
        _write_error(error, stderr or sys.stderr)
        return 2

    # Import the CLI only after rejecting all legacy flags. The CLI itself is
    # config/schema code and imports no framework/provider capability.
    from .cli import main as runtime_main

    return runtime_main(("run", "--strategy-dir", str(Path(runtime_dir))))


__all__ = ["legacy_direct_execution_error", "run_legacy_config_first_cli"]
