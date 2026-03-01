"""Conftest for unit tests - ensures testcommon is importable."""
import sys
import os
from pathlib import Path

# Add tests/ directory to sys.path so 'import testcommon' works
# from any unit test subdirectory (indicators/, analyzers/, etc.)
_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
