"""Fake-only tests for the I15 child-builder source pin gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backtrader_runtime import ctp_i15_td_only_readonly as i15
from backtrader_runtime.ctp_readonly_job_supervisor import FixedChildCommand


_TEST_DIGEST = "a" * 64
_WRONG_DIGEST = "b" * 64


def _binding() -> i15.i12.I12FrontPrecheckBinding:
    return i15.i12.I12FrontPrecheckBinding(0, _TEST_DIGEST)


def _worker_command(tmp_path: Path) -> FixedChildCommand:
    return FixedChildCommand((sys.executable, "-I", "-S", "-B"), tmp_path, {})


def _install_fake_build_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    rendered_digests: list[str] = []
    base_worker = _worker_command(tmp_path)
    artifact_code = f"sys.path.insert(0, {str(tmp_path)!r})\nprint('offline')\n"
    base_artifact = FixedChildCommand(
        (sys.executable, "-I", "-S", "-c", artifact_code), tmp_path, {}
    )

    monkeypatch.setattr(i15.i12, "_is_concrete_path", lambda *_a, **_k: True)
    monkeypatch.setattr(i15.i12, "_fixed_i12_child_command", lambda _binding: base_worker)
    monkeypatch.setattr(
        i15.i12,
        "_fixed_i12_artifact_preflight_command",
        lambda _worker: base_artifact,
    )
    monkeypatch.setattr(
        i15, "_new_i15_pycache_prefix", lambda: tmp_path / "unused-cache-prefix"
    )

    def render_bootstrap(**kwargs: object) -> str:
        digest = kwargs["expected_manifest_sha256"]
        assert type(digest) is str
        rendered_digests.append(digest)
        return "# fake source verifier bootstrap"

    monkeypatch.setattr(i15, "render_i15_source_verifier_bootstrap", render_bootstrap)
    return rendered_digests


def _call_builder(
    name: str, tmp_path: Path, source_digest: object = None
) -> FixedChildCommand | None:
    if name == "child":
        return i15._fixed_i15_child_command(_binding(), source_digest=source_digest)
    return i15._fixed_i15_artifact_preflight_command(
        _worker_command(tmp_path), source_digest=source_digest
    )


@pytest.mark.parametrize("builder", ["child", "artifact"])
@pytest.mark.parametrize(
    ("pinned_digest", "source_digest"),
    [
        (None, _TEST_DIGEST),
        (_TEST_DIGEST, _WRONG_DIGEST),
        (_TEST_DIGEST, None),
        (_TEST_DIGEST, ""),
        (_TEST_DIGEST, _TEST_DIGEST.upper()),
        (123, _TEST_DIGEST),
    ],
    ids=[
        "unset-pin",
        "caller-digest-mismatch",
        "caller-digest-unset",
        "caller-digest-empty",
        "caller-digest-case-mismatch",
        "non-string-pin",
    ],
)
def test_i15_builders_reject_unset_or_mismatched_pin_before_bootstrap(
    builder: str,
    pinned_digest: object,
    source_digest: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i15, "_I15_PINNED_SOURCE_DIGEST", pinned_digest)

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pin rejection must happen before path or bootstrap checks")

    monkeypatch.setattr(i15.i12, "_is_concrete_path", unexpected)
    monkeypatch.setattr(i15, "render_i15_source_verifier_bootstrap", unexpected)

    assert _call_builder(builder, tmp_path, source_digest) is None


@pytest.mark.parametrize("builder", ["child", "artifact"])
def test_i15_builder_accepts_exact_test_only_pin(
    builder: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(i15, "_I15_PINNED_SOURCE_DIGEST", _TEST_DIGEST)
    rendered_digests = _install_fake_build_dependencies(monkeypatch, tmp_path)

    result = _call_builder(builder, tmp_path, _TEST_DIGEST)

    assert type(result) is FixedChildCommand
    assert rendered_digests == [_TEST_DIGEST]
    assert result.env[i15.I15_SOURCE_MANIFEST_ENV] == _TEST_DIGEST
    assert "# fake source verifier bootstrap" in result.argv[-1]
