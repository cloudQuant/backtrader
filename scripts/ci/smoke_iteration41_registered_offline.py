"""Retired Iteration 41 registered-runtime smoke entry point.

The Backtrader-owned runtime and registry were retired in Iteration 53.
No replacement smoke runner is supplied by this entry point.
"""


def main() -> int:
    """Report the removed capability without reading configs or launching processes."""
    import sys

    print(
        "This smoke entry point is retired: backtrader_runtime is unavailable.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
