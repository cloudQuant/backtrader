#!/usr/bin/env python

import sys


# By literal meaning, this class should flush output during output to make it display immediately, but looking at the usage of this class, it doesn't seem to serve this purpose
# Only in btrun file is this file imported, import backtrader.utils.flushfile, when imported it will directly check if this system
# Is win32, if win32 it uses flushfile to create two instances, during initialization uses sys.stdout, sys.stderr these two methods
# In reality, it doesn't seem to serve any purpose. Similar to the py3 file, it may be for compatibility purposes, but who uses python2 anymore, almost never
# So the entire framework appears to have quite a few redundant functions and classes
class flushfile:
    def __init__(self, f):
        self.f = f

    def write(self, x):
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.f.flush()


if sys.platform == "win32":
    sys.stdout = flushfile(sys.stdout)
    sys.stderr = flushfile(sys.stderr)


# Unused class, by type it should be for output
class StdOutDevNull:
    def __init__(self):
        self.stdout = sys.stdout
        sys.stdout = self

    def write(self, x):
        pass

    def flush(self):
        pass

    def stop(self):
        sys.stdout = self.stdout
