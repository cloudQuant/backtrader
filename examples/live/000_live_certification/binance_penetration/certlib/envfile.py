"""Read named variables from the checkout-root `.env`.

Only the names the caller asks for are returned. Values are never printed or
written to evidence; callers only learn which names are present.
"""

from __future__ import annotations

from pathlib import Path


def default_env_path() -> Path:
    # certlib/envfile.py -> certlib -> <venue> -> 000_live_certification -> examples -> repo root
    return Path(__file__).resolve().parents[5] / ".env"


def load_env(names, path=None):
    """Return (values, missing) for the requested variable names."""
    wanted = list(dict.fromkeys(names))
    values = {}
    if path is None:
        path = default_env_path()
    else:
        path = Path(path)
    if not path.is_file():
        return values, list(wanted)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        if key not in wanted or key in values:
            continue
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[key] = value
    missing = [name for name in wanted if name not in values]
    return values, missing
