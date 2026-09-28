"""Inert Popen boundary probe; launched once during R9 prewarm inside a Job."""
import ctypes
import subprocess
import sys
import time

HANDLE = ctypes.c_void_p
DWORD = ctypes.c_uint32
SIZE_T = ctypes.c_size_t
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.MapViewOfFile.argtypes = [HANDLE, DWORD, DWORD, DWORD, SIZE_T]
kernel.MapViewOfFile.restype = ctypes.c_void_p
kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel.UnmapViewOfFile.restype = ctypes.c_int
kernel.SetEvent.argtypes = [HANDLE]
kernel.SetEvent.restype = ctypes.c_int

# LONG fields in r9_custodian.cpp; only the prefix through helperStage is used here.
GO = 0
REQUEST_KIND = 1
REQUEST_SUBMITTED = 2
HELPER_READY = 13
HELPER_STAGE = 14
SHUTDOWN = 15


def main() -> int:
    mode = sys.argv[1]
    mapping_value = int(sys.argv[2])
    ready_value = int(sys.argv[3])
    view = kernel.MapViewOfFile(HANDLE(mapping_value), 0x000F001F, 0, 0, 0)
    if not view:
        return 2
    words = ctypes.cast(view, ctypes.POINTER(ctypes.c_long))
    words[HELPER_READY] = 1
    kernel.SetEvent(HANDLE(ready_value))
    while words[GO] == 0:
        time.sleep(0.001)
    while words[REQUEST_SUBMITTED] == 0 and words[SHUTDOWN] == 0:
        time.sleep(0.001)
    kind = words[REQUEST_KIND]

    if kind == 3 and mode == "before":
        real_popen = subprocess.Popen

        def block_before_create(*_args, **_kwargs):
            words[HELPER_STAGE] = 1  # Entered Popen wrapper; no child has been created.
            time.sleep(3600)
            return real_popen([sys.executable, "-c", "import time; time.sleep(600)"])

        subprocess.Popen = block_before_create
        subprocess.Popen([sys.executable, "-c", "pass"])
    elif kind == 4 and mode == "after":
        real_popen = subprocess.Popen

        def block_after_create_before_return(*_args, **_kwargs):
            child = real_popen([sys.executable, "-c", "import time; time.sleep(600)"])
            words[HELPER_STAGE] = 3  # Child exists in this Job; outer Popen call has not returned.
            time.sleep(3600)
            return child

        subprocess.Popen = block_after_create_before_return
        subprocess.Popen([sys.executable, "-c", "pass"])

    while words[SHUTDOWN] == 0:
        time.sleep(0.001)
    kernel.UnmapViewOfFile(view)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
