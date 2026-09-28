from __future__ import annotations
import ctypes
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
CreateFileW.restype = wintypes.HANDLE
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

with tempfile.TemporaryDirectory(prefix='fake-pyd-custody-') as td:
    root = Path(td)
    pyd = root / 'fake_extension.cp311-win_amd64.pyd'
    replacement = root / 'replacement.pyd'
    original = b'FAKE PLACEHOLDER; NOT A PE IMAGE; NEVER LOADED\n'
    replacement.write_bytes(b'REPLACEMENT MARKER; NEVER LOADED\n')
    pyd.write_bytes(original)
    before = hashlib.sha256(pyd.read_bytes()).hexdigest()
    handle = CreateFileW(str(pyd), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, 0, None)
    h = ctypes.cast(handle, ctypes.c_void_p).value
    if h in (None, INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error())
    write_blocked = False
    write_error_type = None
    write_errno = None
    write_winerror = None
    try:
        with open(pyd, 'r+b') as f:
            f.write(b'ATTACK')
    except OSError as exc:
        write_error_type = type(exc).__name__
        write_errno = getattr(exc, 'errno', None)
        write_winerror = getattr(exc, 'winerror', None)
        write_blocked = isinstance(exc, PermissionError) and write_errno == 13
    replace_blocked = False
    replace_error_type = None
    replace_errno = None
    replace_winerror = None
    try:
        os.replace(replacement, pyd)
    except OSError as exc:
        replace_error_type = type(exc).__name__
        replace_errno = getattr(exc, 'errno', None)
        replace_winerror = getattr(exc, 'winerror', None)
        replace_blocked = isinstance(exc, PermissionError) and replace_winerror in (5, 32, 33)
    after_denied_attempts = hashlib.sha256(pyd.read_bytes()).hexdigest()
    close_ok = bool(CloseHandle(h))
    moved_after_release = False
    if close_ok:
        os.replace(pyd, root / 'after-release.pyd')
        moved_after_release = True
    result = {
        'python': sys.version.split()[0],
        'fake_suffix': '.pyd',
        'payload_kind': 'plain-text placeholder; not valid PE; never loaded',
        'original_sha256': before,
        'hash_after_denied_attempts': after_denied_attempts,
        'write_blocked': write_blocked,
        'write_error_type': write_error_type,
        'write_errno': write_errno,
        'write_winerror': write_winerror,
        'replace_blocked': replace_blocked,
        'replace_error_type': replace_error_type,
        'replace_errno': replace_errno,
        'replace_winerror': replace_winerror,
        'close_handle_succeeded': close_ok,
        'rename_after_release_succeeded': moved_after_release,
        'loaded_native_module': False,
        'pass': bool(write_blocked and replace_blocked and close_ok and moved_after_release and before == after_denied_attempts),
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    if not result['pass']:
        raise SystemExit(1)
