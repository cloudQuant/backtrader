"""Iteration-41 optional-component matrix: gateway/ZMQ transport for 000 cases.

`optional16` is the sixteen-combination acceptance grid
(``direct``/``gateway_zmq`` x execution x risk x monitor). This package owns the
transport half of that grid for the Binance USD-M demo suite:

* `spec.TopologySpec` / `spec.from_config` / `spec.combo_id` — pure validation
  and the stable combination ids used in evidence (``direct-e0-r0-m0``...).
* `gateway_server.GatewayServer` — a **loopback-only** server process/object
  that *owns* one provider session (constructed through ``certlib.make_client``
  with the ``direct`` topology) and serves a closed command whitelist
  (connect, account_config, balances, position_risk, open_orders, filters,
  mark_price, place_order, cancel_order, query_order, describe) over the dev
  SDK ``bt_api_transport_zmq`` ROUTER/DEALER envelope, or a documented
  stdlib TCP+JSON fallback when that package cannot be imported offline.
* `gateway_client.GatewayClient` — the duck-typed client the certification
  cases already use, forwarding every call to the server and recording
  ``.calls`` locally for evidence.
* ``optional16.components.wrap_client(client, config, topology, env)`` is
  provided by the sibling component task; when that module is absent the
  suite's `component_not_implemented` behaviour is preserved.

Every command is appended to a per-run JSONL journal (``commands.jsonl``) with
its request id, params, outcome, error string and result digest. The client
token travels under the payload key ``auth`` (the transport wire layer rejects
secret-shaped field names) and is never journaled.

Live invocation the owner runs (from ``examples/000_live_certification``)
--------------------------------------------------------------------------
Embedded server (each case process starts and stops its own gateway)::

    C:/anaconda3/python.exe binance_penetration/cases/C01/run.py --live --transport gateway_zmq
    C:/anaconda3/python.exe binance_penetration/cases/T03/run.py --live --allow-write --transport gateway_zmq

One shared server reused by both cases (server terminal / matrix runner)::

    C:/anaconda3/python.exe optional16/gateway_server.py \
        --config binance_penetration/cases/C01/config.yaml \
        --journal-dir D:/temp/optional16-journal
    # prints {"status": "READY", "connection_string": "zmq@127.0.0.1:<port>:<token>", ...}

    set BT_CERT_GATEWAY=zmq@127.0.0.1:<port>:<token>
    C:/anaconda3/python.exe binance_penetration/cases/C01/run.py --live --transport gateway_zmq
    C:/anaconda3/python.exe binance_penetration/cases/T03/run.py --live --allow-write --transport gateway_zmq

Matrix runner (in-process, no live account work by itself)::

    from optional16 import GatewayServer, GatewayClient, matrix_specs, combo_id

Security limits are documented in the `gateway_server` module docstring: the
bind is always 127.0.0.1 with a random per-run port and a random shared token,
the transport's CurveZMQ/ZAP remote-key ACL is intentionally unused for
loopback, and the token is not an OS-isolation boundary. The gateway package's
durable ``GatewayCommandRouter`` chain is deliberately not wired; only the
transport package's versioned envelope plus the local JSONL journal are used.
"""

from __future__ import annotations

from .gateway_client import (
    ClientFrozen,
    GatewayClient,
    GatewayCommandUncertain,
    GatewayError,
    GatewayRejected,
    GatewayUnavailable,
)
from .gateway_server import CommandJournal, GatewayServer, build_direct_provider
from .spec import (
    COMPONENT_FLAGS,
    TRANSPORTS,
    TopologyError,
    TopologySpec,
    combo_id,
    from_config,
    matrix_ids,
    matrix_specs,
)

__all__ = [
    "COMPONENT_FLAGS",
    "ClientFrozen",
    "CommandJournal",
    "GatewayClient",
    "GatewayCommandUncertain",
    "GatewayError",
    "GatewayRejected",
    "GatewayServer",
    "GatewayUnavailable",
    "TRANSPORTS",
    "TopologyError",
    "TopologySpec",
    "build_direct_provider",
    "combo_id",
    "from_config",
    "matrix_ids",
    "matrix_specs",
]
