"""Windows-only probes for retained installed-artifact handles."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from backtrader_runtime.ctp_windows_artifact_custody import (
    WindowsArtifactCustody,
    WindowsArtifactCustodyError,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing")


def _secure_test_root() -> Path:
    parent = Path(os.environ["USERPROFILE"]) / "Temp"
    if not parent.is_dir():
        pytest.skip("protected per-user Temp directory is unavailable")
    return Path(tempfile.mkdtemp(prefix="iter41-custody-", dir=parent))


def test_retained_source_handle_blocks_concurrent_replace_before_import() -> None:
    root = _secure_test_root()
    source = root / "pinned_module.py"
    marker = root / "executed.txt"
    replacement = root / "replacement.py"
    source_bytes = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('pinned', encoding='ascii')\n"
        "VALUE = 41\n"
    ).encode()
    replacement_bytes = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('malicious', encoding='ascii')\n"
    ).encode()
    source.write_bytes(source_bytes)
    replacement.write_bytes(replacement_bytes)
    custody = WindowsArtifactCustody.acquire(
        str(root),
        (source.name,),
        expected_sha256={source.name: hashlib.sha256(source_bytes).hexdigest()},
    )
    attempts: list[tuple[str, str, int | None]] = []

    def replace_source() -> None:
        try:
            source.write_bytes(b"VALUE = 99\n")
        except OSError as error:
            attempts.append(
                ("overwrite", type(error).__name__, getattr(error, "winerror", None))
            )
        else:
            attempts.append(("overwrite", "write_succeeded", None))
        try:
            os.replace(replacement, source)
        except OSError as error:
            attempts.append(
                ("replace", type(error).__name__, getattr(error, "winerror", None))
            )
        else:
            attempts.append(("replace", "replace_succeeded", None))

    thread = threading.Thread(target=replace_source)
    try:
        thread.start()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert attempts[0][:2] == ("overwrite", "PermissionError")
        assert attempts[1] == ("replace", "PermissionError", 32)

        spec = importlib.util.spec_from_file_location("pinned_module", source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.VALUE == 41
        assert marker.read_text(encoding="ascii") == "pinned"
        assert custody.read(source.name) == source_bytes
        custody.verify_current()
    finally:
        custody.close()
        shutil.rmtree(root, ignore_errors=True)


def test_untrusted_writable_candidate_root_is_rejected_before_file_read() -> None:
    # The r1 source tree under D:\temp is intentionally writable and must not
    # be accepted as an installed artifact root.
    source = Path(__file__).resolve().parents[3] / "README.md"
    with pytest.raises(WindowsArtifactCustodyError) as raised:
        WindowsArtifactCustody.acquire(
            str(source.parent),
            (source.name,),
            expected_sha256={
                source.name: hashlib.sha256(source.read_bytes()).hexdigest()
            },
        )
    assert raised.value.reason == "windows_acl_untrusted_write_grant"


def test_directory_handle_does_not_claim_to_prevent_new_child_creation() -> None:
    root = _secure_test_root()
    source = root / "pinned.py"
    raw = b"VALUE = 1\n"
    source.write_bytes(raw)
    custody = WindowsArtifactCustody.acquire(
        str(root),
        (source.name,),
        expected_sha256={source.name: hashlib.sha256(raw).hexdigest()},
    )
    child = root / "unexpected_module.py"
    try:
        # Windows share modes pin existing objects; they are not a substitute
        # for a directory DACL when the current user can add new names.
        child.write_bytes(b"MARKER = True\n")
        assert child.read_bytes() == b"MARKER = True\n"
    finally:
        custody.close()
        shutil.rmtree(root, ignore_errors=True)
