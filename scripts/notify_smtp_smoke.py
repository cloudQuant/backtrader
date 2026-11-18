#!/usr/bin/env python3
"""Send one SMTP notification through backtrader.notifications from project .env.

Credentials are read from the repository .env (BT_NOTIFY_EMAIL_*) or the
process environment; they are never printed. Run with --dry-run to only
validate that the email channel is configured.
"""
from __future__ import annotations
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env(path: pathlib.Path) -> None:
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key.startswith("BT_NOTIFY_") and value and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_env(ROOT / ".env")
    import backtrader as bt
    try:
        bt.configure_notifications_from_env()
    except Exception as exc:
        print(f"SMTP notification not configured: {exc}")
        return 2
    if "--dry-run" in sys.argv:
        print("SMTP notification channel configured")
        return 0
    results = bt.send_message("backtrader SMTP smoke test", level="info", wait=True)
    print(f"send results: {results}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
