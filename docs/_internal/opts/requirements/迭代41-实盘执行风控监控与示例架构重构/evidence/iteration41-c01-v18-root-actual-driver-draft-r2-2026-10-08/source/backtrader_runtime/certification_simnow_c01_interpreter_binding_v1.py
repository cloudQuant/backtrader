"""Fixed CPython image and SDK-consumer binding for SimNow C01.

This module contains public software-location pins only.  Callers load its
exact source bytes through their own source-pinned boundary.  It has no
provider, SDK, credential, environment-variable, or network behavior.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import ntpath
import os
from pathlib import Path
import stat
import struct
import sys
from typing import Optional


BINDING_ID = "simnow.c01.interpreter-binding.v1"
PYTHON_VERSION = (3, 11, 5)
PLATFORM = "win32"
POINTER_BITS = 64

CPYTHON_EXECUTABLE = r"C:\anaconda3\python.exe"
CPYTHON_EXECUTABLE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
CPYTHON_DLL = r"C:\anaconda3\python311.dll"
CPYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
VENV_ROOT = r"D:\temp\iteration41-g4-pin-parent-abi-check-20260928\venv-b-exact-origin"
VENV_CONFIG = VENV_ROOT + r"\pyvenv.cfg"
VENV_CONFIG_SHA256 = "150def367c7fcd432ae7a1f38e8d01faf6a99a4ace57d35b3a3e241fbc23e4a9"
SDK_SITE_PACKAGES = VENV_ROOT + r"\Lib\site-packages"

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
_MAX_PYTHON_DLL_BYTES = 128 * 1024 * 1024
_MAX_VENV_CONFIG_BYTES = 4096


def _normalized_windows_path(value: object) -> Optional[str]:
    if type(value) is not str or not value or "\x00" in value:
        return None
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith(("\\\\?\\", "\\??\\")):
        value = value[4:]
    if not ntpath.isabs(value):
        return None
    return ntpath.normcase(ntpath.normpath(value))


def runtime_identity_matches(
    *,
    os_name: object,
    platform_name: object,
    implementation_name: object,
    version: object,
    pointer_bits: object,
    sys_executable: object,
    process_image_path: object,
    python_dll_path: object,
) -> bool:
    """Match interpreter facts without accepting a venv launcher as CPython."""

    expected_executable = _normalized_windows_path(CPYTHON_EXECUTABLE)
    expected_dll = _normalized_windows_path(CPYTHON_DLL)
    return bool(
        os_name == "nt"
        and platform_name == PLATFORM
        and implementation_name == "cpython"
        and type(version) is tuple
        and version == PYTHON_VERSION
        and type(pointer_bits) is int
        and pointer_bits == POINTER_BITS
        and expected_executable is not None
        and expected_dll is not None
        and _normalized_windows_path(sys_executable) == expected_executable
        and _normalized_windows_path(process_image_path) == expected_executable
        and _normalized_windows_path(python_dll_path) == expected_dll
    )


def bytes_match_sha256(data: object, expected: object, *, maximum_bytes: int) -> bool:
    if (
        type(data) is not bytes
        or type(expected) is not str
        or len(expected) != 64
        or type(maximum_bytes) is not int
        or maximum_bytes <= 0
        or len(data) > maximum_bytes
    ):
        return False
    if any(character not in "0123456789abcdef" for character in expected):
        return False
    return hashlib.sha256(data).hexdigest() == expected


def _path_has_no_reparse_components(path: Path, *, directory: bool) -> bool:
    if not path.is_absolute():
        return False
    parts = path.parts
    if not parts:
        return False
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current = current / part
        try:
            info = current.lstat()
        except OSError:
            return False
        if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
        is_final = index == len(parts) - 1
        if not is_final and not stat.S_ISDIR(info.st_mode):
            return False
    try:
        final = path.lstat()
    except OSError:
        return False
    if getattr(final, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(
        final.st_mode
    ):
        return False
    return stat.S_ISDIR(final.st_mode) if directory else stat.S_ISREG(final.st_mode)


def _path_matches_sha256(path_text: str, expected: str, maximum_bytes: int) -> bool:
    path = Path(path_text)
    if not _path_has_no_reparse_components(path, directory=False):
        return False
    try:
        before = path.stat()
        if before.st_size <= 0 or before.st_size > maximum_bytes:
            return False
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    return False
                digest.update(chunk)
        after = path.stat()
    except OSError:
        return False
    return bool(
        total == before.st_size == after.st_size
        and before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_mtime_ns == after.st_mtime_ns
        and digest.hexdigest() == expected
    )


def _loaded_module_path(module_name: Optional[str]) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_module = kernel32.GetModuleHandleW
        get_module.argtypes = [wintypes.LPCWSTR]
        get_module.restype = wintypes.HMODULE
        get_path = kernel32.GetModuleFileNameW
        get_path.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        get_path.restype = wintypes.DWORD
        handle = get_module(module_name)
        if not handle:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_path(handle, buffer, len(buffer))
        if not length or length >= len(buffer):
            return None
        return buffer.value
    except Exception:
        return None


def _current_runtime_facts() -> dict[str, object]:
    return {
        "os_name": os.name,
        "platform_name": sys.platform,
        "implementation_name": sys.implementation.name,
        "version": tuple(sys.version_info[:3]),
        "pointer_bits": struct.calcsize("P") * 8,
        "sys_executable": sys.executable,
        "process_image_path": _loaded_module_path(None),
        "python_dll_path": _loaded_module_path("python311.dll"),
    }


def verify_current_runtime() -> bool:
    """Verify this process image, loaded CPython DLL, and fixed SDK consumer."""

    try:
        facts = _current_runtime_facts()
        if not runtime_identity_matches(**facts):
            return False
    except Exception:
        return False
    if not _path_matches_sha256(
        CPYTHON_EXECUTABLE, CPYTHON_EXECUTABLE_SHA256, _MAX_EXECUTABLE_BYTES
    ):
        return False
    if not _path_matches_sha256(CPYTHON_DLL, CPYTHON_DLL_SHA256, _MAX_PYTHON_DLL_BYTES):
        return False
    if not _path_matches_sha256(VENV_CONFIG, VENV_CONFIG_SHA256, _MAX_VENV_CONFIG_BYTES):
        return False
    return _path_has_no_reparse_components(Path(SDK_SITE_PACKAGES), directory=True)


__all__ = [
    "BINDING_ID",
    "CPYTHON_DLL",
    "CPYTHON_DLL_SHA256",
    "CPYTHON_EXECUTABLE",
    "CPYTHON_EXECUTABLE_SHA256",
    "PLATFORM",
    "POINTER_BITS",
    "PYTHON_VERSION",
    "SDK_SITE_PACKAGES",
    "VENV_CONFIG",
    "VENV_CONFIG_SHA256",
    "VENV_ROOT",
    "bytes_match_sha256",
    "runtime_identity_matches",
    "verify_current_runtime",
]
