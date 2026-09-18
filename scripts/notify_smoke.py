#!/usr/bin/env python
"""Send one real notification per channel - local manual smoke test only.

This script performs **real network I/O** and therefore never runs in CI. It
reads credentials from the environment, reports which channels it could not
verify, and prints a credential-free ``SendResult`` per channel.

Environment layout (see ``docs/NOTIFICATIONS_GUIDELINES.md``)::

    BT_NOTIFY_CHANNELS=dingtalk,telegram
    BT_NOTIFY_DINGTALK_ACCESS_TOKEN=...
    BT_NOTIFY_DINGTALK_SECRET=...              # optional (signed robots)
    BT_NOTIFY_TELEGRAM_BOT_TOKEN=...
    BT_NOTIFY_TELEGRAM_CHAT_ID=...

Usage::

    python scripts/notify_smoke.py                     # every channel with credentials
    python scripts/notify_smoke.py --channels ntfy     # only the listed channels
    python scripts/notify_smoke.py --list-unverified   # what is missing, then exit
    python scripts/notify_smoke.py --message "hello" --level warning
"""

import argparse
import os
import sys

# Running ``python scripts/notify_smoke.py`` puts ``scripts/`` on sys.path, so an
# older non-editable copy in site-packages would win over this repository. Put
# the repository root first so the smoke test exercises the working tree.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import backtrader as bt  # noqa: E402 - sys.path is prepared above
from backtrader.notifications import PUBLIC_CHANNELS, channel_requires  # noqa: E402

DEFAULT_PREFIX = "BT_NOTIFY_"


def _required_fields(channel_id):
    """Return the credential fields a channel needs.

    Args:
        channel_id: Public channel id.

    Returns:
        tuple: Required field names.
    """
    return channel_requires(channel_id)


def _channel_is_configured(channel_id, prefix):
    """Return whether every required credential is present in the environment.

    Args:
        channel_id: Public channel id.
        prefix: Environment variable prefix.

    Returns:
        bool: Whether the channel can be attempted.
    """
    base = "{0}{1}_".format(prefix, channel_id.upper())
    return all(os.environ.get(base + field.upper()) for field in _required_fields(channel_id))


def _parse_args(argv=None):
    """Parse command line arguments.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--channels",
        default="",
        help="comma separated channel ids; default: all channels with credentials",
    )
    parser.add_argument(
        "--list-unverified", action="store_true", help="list channels missing credentials and exit"
    )
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="environment prefix")
    parser.add_argument("--message", default="backtrader notification smoke test", help="body text")
    parser.add_argument("--level", default="info", help="info|warning|error|critical")
    return parser.parse_args(argv)


def main(argv=None):
    """Run the smoke test.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        int: Process exit code (0 when every attempted channel succeeded).
    """
    args = _parse_args(argv)
    prefix = args.prefix
    if args.channels:
        requested = [item.strip() for item in args.channels.split(",") if item.strip()]
    else:
        requested = list(PUBLIC_CHANNELS)
    unknown = [item for item in requested if item not in PUBLIC_CHANNELS]
    if unknown:
        print("unknown channel(s): {0}".format(", ".join(unknown)))
        print("known channels: {0}".format(", ".join(PUBLIC_CHANNELS)))
        return 2

    configured = [item for item in requested if _channel_is_configured(item, prefix)]
    unverified = [item for item in requested if item not in configured]

    if args.list_unverified:
        if unverified:
            print("channels without complete credentials ({0}):".format(prefix))
            for channel_id in unverified:
                missing = [
                    field
                    for field in _required_fields(channel_id)
                    if not os.environ.get(
                        "{0}{1}_{2}".format(prefix, channel_id.upper(), field.upper())
                    )
                ]
                print("  {0}: missing {1}".format(channel_id, ", ".join(missing)))
        else:
            print("all requested channels have credentials")
        return 0

    if not configured:
        print("no requested channel has complete credentials; nothing to send")
        print("run with --list-unverified to see what is missing")
        return 1

    os.environ[prefix + "CHANNELS"] = ",".join(configured)
    try:
        bt.configure_notifications_from_env(prefix=prefix)
        result = bt.send_message(args.message, level=args.level, wait=True)
    except ValueError as exc:
        print("configuration error: {0}".format(exc))
        return 2

    print("mode={0} accepted={1} reason={2}".format(result.mode, result.accepted, result.reason))
    exit_code = 0
    for outcome in result.outcomes:
        print(
            "  {0:<16} ok={1!s:<5} category={2:<14} attempts={3} elapsed_ms={4:.0f} error={5}".format(
                outcome.channel,
                outcome.ok,
                outcome.error_category or "-",
                outcome.attempts,
                outcome.elapsed_ms,
                outcome.error or "-",
            )
        )
        if not outcome.ok:
            exit_code = 1
    if unverified:
        print("not attempted (no credentials): {0}".format(", ".join(unverified)))
    bt.reset_notifications()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
