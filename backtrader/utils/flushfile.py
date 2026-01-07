#!/usr/bin/env python
"""Flush File Module - Auto-flushing file wrapper for Windows.

This module provides a wrapper for file-like objects that automatically
flushes after each write. On Windows platforms, it replaces sys.stdout
and sys.stderr with auto-flushing versions to ensure immediate output.

Classes:
    flushfile: Wrapper that auto-flushes after each write.
    StdOutDevNull: Null output device that suppresses stdout.

Note:
    This is primarily for Windows compatibility where output buffering
    can cause delayed display of stdout/stderr.
"""

import sys


# By literal meaning, this class should flush output during output to make it display immediately, but looking at the usage of this class, it doesn't seem to serve this purpose
# Only in btrun file is this file imported, import backtrader.utils.flushfile, when imported it will directly check if this system
# Is win32, if win32 it uses flushfile to create two instances, during initialization uses sys.stdout, sys.stderr these two methods
# In reality, it doesn't seem to serve any purpose. Similar to the py3 file, it may be for compatibility purposes, but who uses python2 anymore, almost never
# So the entire framework appears to have quite a few redundant functions and classes
class flushfile:
    """File wrapper that auto-flushes after each write.

    This class wraps a file-like object and ensures that each write
    operation is immediately flushed to the underlying file descriptor.

    Attributes:
        f: The underlying file-like object.

    Note:
        On Windows, this module automatically wraps sys.stdout and
        sys.stderr with flushfile instances.
    """

    def __init__(self, f):
        """Initialize the flushfile wrapper.

        Args:
            f: File-like object to wrap (typically sys.stdout or sys.stderr).
        """
        self.f = f

    def write(self, x):
        """Write data to the file and immediately flush.

        Args:
            x: Data to write to the file.
        """
        self.f.write(x)
        self.f.flush()

    def flush(self):
        """Flush the underlying file buffer."""
        self.f.flush()


if sys.platform == "win32":
    sys.stdout = flushfile(sys.stdout)
    sys.stderr = flushfile(sys.stderr)


# Unused class, by type it should be for output
class StdOutDevNull:
    """Null output device that suppresses stdout.

    When active, all writes to stdout are discarded. The original
    stdout can be restored by calling the stop() method.

    Attributes:
        stdout: The original sys.stdout saved for restoration.
    """

    def __init__(self):
        """Initialize StdOutDevNull and replace sys.stdout."""
        self.stdout = sys.stdout
        sys.stdout = self

    def write(self, x):
        """Discard written data instead of outputting.

        Args:
            x: Data to discard.
        """
        pass

    def flush(self):
        """No-op flush method for compatibility."""
        pass

    def stop(self):
        """Restore the original sys.stdout."""
        sys.stdout = self.stdout
