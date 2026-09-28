"""The legacy second CTP production-config writer must remain retired."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

import pytest

import backtrader_runtime.cli as cli
import backtrader_runtime.ctp_production_config_setup as setup
from backtrader_runtime.errors import CONFIG_SCHEMA_UNSUPPORTED, RuntimeConfigError


class _ObservedPath(os.PathLike):
    def __init__(self, path: Path):
        self.path = path
        self.conversions = 0

    def __fspath__(self):
        self.conversions += 1
        return os.fspath(self.path)


class _ObservedSources:
    def __init__(self, source):
        self.source = source
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return iter(((self.source, "yaml"),))


@pytest.mark.parametrize("api", ["single_source", "source_list"])
def test_legacy_writer_rejects_before_source_or_target_io(tmp_path, monkeypatch, api):
    source = _ObservedPath(tmp_path / "unread-source.yaml")
    source_list = _ObservedSources(source)
    target_path = tmp_path / "existing-runtime"
    target_path.mkdir()
    target = _ObservedPath(target_path)

    def reject_io(*_args, **_kwargs):
        raise AssertionError("the retired writer must not perform filesystem I/O")

    with monkeypatch.context() as io_guard:
        io_guard.setattr(builtins, "open", reject_io)
        io_guard.setattr(io, "open", reject_io)
        io_guard.setattr(os, "open", reject_io)
        io_guard.setattr(Path, "open", reject_io)
        with pytest.raises(RuntimeConfigError) as rejected:
            if api == "single_source":
                setup.prepare_ctp_production_config(
                    source, source_format="yaml", runtime_dir=target
                )
            else:
                setup.prepare_ctp_production_config_sources(source_list, runtime_dir=target)

    assert rejected.value.reason == "separate_production_config_not_supported"
    assert rejected.value.code == CONFIG_SCHEMA_UNSUPPORTED
    assert source.conversions == 0
    assert target.conversions == 0
    assert source_list.iterations == 0
    assert not (target_path / "config.yaml").exists()


def test_retired_cli_rejects_without_reading_a_source_or_creating_config(tmp_path):
    target = tmp_path / "runtime-production"
    target.mkdir()

    result_output = io.StringIO()
    error_output = io.StringIO()
    result = cli.main(
        ["prepare-ctp-production-config", "--source-yaml", str(tmp_path / "unread.yaml")],
        stdout=result_output,
        stderr=error_output,
    )

    assert result == 2
    assert result_output.getvalue() == ""
    assert '"reason": "separate_production_config_not_supported"' in error_output.getvalue()
    assert "examples/013_3_sa_midfreq_simnow/runtime-ctp-private" in error_output.getvalue()
    assert not (target / "config.yaml").exists()
