# Root current-profile CTP read-only login caller R1 review

**Decision: GO — bounded Root-owned profile-login attempt only.** This is a
static source review; no caller/helper was imported or executed, and no SDK,
native, provider, or private configuration data was accessed. It is not login,
account, or formal-case acceptance.

## Reviewed pins

| Public source | Bytes | SHA-256 |
| --- | ---: | --- |
| `.codex-tmp/i51_root_current_profile_login_r1_20261027.py` | 11,631 | `6f5755d2e2455e3492f0337c38635861b719dbee0c2358cf599edc93104af589` |
| `.codex-tmp/i51_root_readonly_discovery_r3_20261027.py` | 14,316 | `0fbd847844d0073b3a89867e2a9f449a3beeef32f93f7e74b31061b043723313` |
| `examples/unified/028_alpha003_simnow_minute/protected_simnow.py` | 8,556 | `c4269bb9b78e40fd60843e32af5616dece5052d621258add12ba82f9696c1982` |
| `examples/unified/028_alpha003_simnow_minute/discovery_lifecycle.py` | 24,256 | `305ecf7cb89ccf8aee15179312fbf4b311f41ead7e65a97b01e19c0e3ccb3f3d` |

## Basis and limits

The new caller selects sealed config index `0`, requires the helper's exact
`set1_group1_vpn` profile label, and uses `protected_simnow_store_config`.
That helper validates the selected sealed pair against the official SimNow
front mapping, checks the exact TCP pair, verifies the pinned installed SDK
distributions inside its trusted import context, resolves and seals credentials,
and exposes only a redacted live handoff. The caller contains no `run.py`
import, no market-query call, and no dependency on the previously accepted
market-discovery result. It creates a direct CTP `RegisteredSimStore` with
`allow_writes=False`, passes `ctp_join_observer=False` and the existing
`allow_zero_login_response=True`, waits at most 30 seconds for read-only
readiness, and validates a formatted TradingDay and positive connection
generation. It checks the typed MD login diagnostic; the read-only-accepted
mode requires no active MD identity. The caller does not invoke an MD auth
identity constructor or any order/query API.

The `finally` path invokes the pinned `close_discovery_store` once for a
created Store. That helper requires the discovery-only topology, normal Store
shutdown when connected, typed SDK receipts for both clients, and quiescent
Store health; on uncertainty it raises with the exact Store/client custody
retained. The caller keeps the handoff stack and native-output mute open on
incomplete close and reports blocked custody instead of claiming closure.
Public output is a finite projection; private configuration values and raw
exceptions are not serialized. Root's separate preflight is required to keep
the new private TEMP owner-only and to bind the fresh installed consumer and
interactive host before invocation.

One evidence distinction: `md_zero_response_readonly_compatibility=True`
records that the caller enabled the compatibility option; it does not prove
that this invocation received a zero login response. `md_login_mode` and
`authenticated_md_identity_present` separately record the observed diagnostic
mode and identity state. An ordinary `ACCEPTED` diagnostic is permitted and
its identity state is reported; only `READ_ONLY_ACCEPTED` requires absence.
Treat the result as profile-login/TradingDay evidence only, never as proof of
a zero-response event or as a rerun of accepted market discovery.
