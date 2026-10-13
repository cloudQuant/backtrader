"""Retired Optional16 live gateway-capability acceptance command.

The historical source and records remain in the repository. This entrypoint
is kept as a stable command target and performs no config, credential,
provider, journal, or evidence I/O.
"""

import json


def main(argv=None):
    """Report that the Optional16 acceptance path is retired."""
    print(json.dumps({"status": "BLOCKED", "reason": "optional16_acceptance_retired"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
