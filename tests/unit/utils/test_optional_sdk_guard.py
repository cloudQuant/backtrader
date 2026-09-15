"""Optional dependency skips must never hide an incompatible installed SDK."""

from importlib import metadata

import pytest

from tests.test_utils import optional_sdk as guard


def test_absent_distribution_skips_before_import(monkeypatch):
    def absent(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(guard.metadata, "distribution", absent)
    monkeypatch.setattr(
        guard.importlib, "import_module", lambda name: pytest.fail("must not import absent SDK")
    )
    with pytest.raises(pytest.skip.Exception, match="bt_api_py is not installed"):
        guard.optional_sdk()


@pytest.mark.parametrize("error_type", [ImportError, ModuleNotFoundError])
def test_installed_sdk_import_failure_is_not_a_skip(monkeypatch, error_type):
    monkeypatch.setattr(guard.metadata, "distribution", lambda name: object())

    def incompatible(name):
        raise error_type("installed SDK has a broken dependency or API")

    monkeypatch.setattr(guard.importlib, "import_module", incompatible)
    with pytest.raises(error_type, match="installed SDK"):
        guard.optional_sdk()


def test_installed_sdk_is_returned_without_api_substitution(monkeypatch):
    module = object()
    monkeypatch.setattr(guard.metadata, "distribution", lambda name: object())
    monkeypatch.setattr(guard.importlib, "import_module", lambda name: module)
    assert guard.optional_sdk() is module


def test_invalid_distribution_metadata_is_not_a_skip(monkeypatch):
    def invalid(name):
        raise ValueError("broken distribution metadata")

    monkeypatch.setattr(guard.metadata, "distribution", invalid)
    with pytest.raises(ValueError, match="broken distribution"):
        guard.optional_sdk()
