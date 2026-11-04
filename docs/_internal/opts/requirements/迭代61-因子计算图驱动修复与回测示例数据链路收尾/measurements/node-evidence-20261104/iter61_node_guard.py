import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path, config):
    name = collection_path.name
    if name == "config.yaml" or name.startswith(".env") or name in {".ssh", ".aws", ".kube", ".config", ".codex", ".netrc", ".condarc", ".pypirc", "credentials", "credentials.json"}:
        return True
    return None
