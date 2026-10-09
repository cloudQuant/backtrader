"""Pure checks for the fixed SimNow C01 CPython/SDK consumer binding."""

from __future__ import annotations

import hashlib

import pytest

from backtrader_runtime import certification_simnow_c01_interpreter_binding_v1 as binding


def _facts(**overrides):
    facts = {
        "os_name": "nt",
        "platform_name": "win32",
        "implementation_name": "cpython",
        "version": (3, 11, 5),
        "pointer_bits": 64,
        "sys_executable": binding.CPYTHON_EXECUTABLE,
        "process_image_path": binding.CPYTHON_EXECUTABLE,
        "python_dll_path": binding.CPYTHON_DLL,
    }
    facts.update(overrides)
    return facts


def test_exact_direct_cpython_image_dll_and_consumer_are_accepted():
    assert binding.runtime_identity_matches(**_facts()) is True
    assert (
        binding.runtime_identity_matches(
            **_facts(
                sys_executable=r"\\?\C:\anaconda3\python.exe",
                process_image_path=r"\\?\C:\anaconda3\python.exe",
                python_dll_path=r"\\?\C:\anaconda3\python311.dll",
            )
        )
        is True
    )


@pytest.mark.parametrize(
    "override",
    (
        {"sys_executable": binding.VENV_ROOT + r"\Scripts\python.exe"},
        {"process_image_path": binding.VENV_ROOT + r"\Scripts\python.exe"},
        {"python_dll_path": binding.VENV_ROOT + r"\python311.dll"},
        {"version": (3, 11, 4)},
        {"version": (3, 11)},
        {"pointer_bits": 32},
        {"implementation_name": "pypy"},
        {"platform_name": "linux"},
        {"os_name": "posix"},
    ),
)
def test_venv_redirector_and_unsupported_runtime_facts_are_rejected(override):
    assert binding.runtime_identity_matches(**_facts(**override)) is False


def test_bounded_byte_digest_comparison_is_exact():
    payload = b"approved fixture bytes"
    digest = hashlib.sha256(payload).hexdigest()
    assert binding.bytes_match_sha256(payload, digest, maximum_bytes=len(payload)) is True
    assert binding.bytes_match_sha256(payload + b"x", digest, maximum_bytes=len(payload)) is False
    assert binding.bytes_match_sha256(payload, "A" * 64, maximum_bytes=100) is False
    assert binding.bytes_match_sha256("not bytes", digest, maximum_bytes=100) is False


def test_runtime_verification_uses_only_fixed_public_paths_and_hash_pins(monkeypatch):
    monkeypatch.setattr(binding, "_current_runtime_facts", lambda: _facts())
    checked = []

    def digest_check(path, expected, maximum):
        checked.append((path, expected, maximum))
        return True

    monkeypatch.setattr(binding, "_path_matches_sha256", digest_check)
    monkeypatch.setattr(binding, "_path_has_no_reparse_components", lambda *_a, **_k: True)

    assert binding.verify_current_runtime() is True
    assert [row[:2] for row in checked] == [
        (binding.CPYTHON_EXECUTABLE, binding.CPYTHON_EXECUTABLE_SHA256),
        (binding.CPYTHON_DLL, binding.CPYTHON_DLL_SHA256),
        (binding.VENV_CONFIG, binding.VENV_CONFIG_SHA256),
    ]


def test_runtime_verification_rejects_image_mismatch_before_file_checks(monkeypatch):
    monkeypatch.setattr(
        binding,
        "_current_runtime_facts",
        lambda: _facts(process_image_path=binding.VENV_ROOT + r"\Scripts\python.exe"),
    )
    monkeypatch.setattr(
        binding,
        "_path_matches_sha256",
        lambda *_a, **_k: pytest.fail("hash reads must not follow a mismatched process image"),
    )
    assert binding.verify_current_runtime() is False


def test_runtime_verification_rejects_any_changed_runtime_pin(monkeypatch):
    monkeypatch.setattr(binding, "_current_runtime_facts", lambda: _facts())
    checked = []

    def digest_check(path, expected, maximum):
        checked.append(path)
        return path != binding.VENV_CONFIG

    monkeypatch.setattr(binding, "_path_matches_sha256", digest_check)
    monkeypatch.setattr(binding, "_path_has_no_reparse_components", lambda *_a, **_k: True)

    assert binding.verify_current_runtime() is False
    assert checked == [binding.CPYTHON_EXECUTABLE, binding.CPYTHON_DLL, binding.VENV_CONFIG]
