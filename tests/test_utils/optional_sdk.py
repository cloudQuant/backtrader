"""Skip optional SDK tests only when their distribution is not installed.

Unlike a broad importorskip, this must expose broken installed distributions,
missing API symbols, native-library load failures, and dependency mismatches.
"""

import importlib
from importlib import metadata

import pytest


def optional_sdk(module_name="bt_api_py", *, allow_module_level=False):
    """Import the optional SDK module, skipping when its distribution is absent."""
    distribution = module_name.split(".", 1)[0]
    try:
        metadata.distribution(distribution)
    except metadata.PackageNotFoundError:
        pytest.skip(
            f"optional SDK distribution {distribution} is not installed",
            allow_module_level=allow_module_level,
        )
    return importlib.import_module(module_name)
