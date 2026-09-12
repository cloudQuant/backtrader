# Local CTP bundle authorization builder

`ctp_options_simnow_authorization.py` only builds the exact V2 authorization
grant and arming proof from caller-supplied Stage A, Stage B, bundle-preflight,
and runtime identity evidence. It does not connect, read `.env`, create a CTP
client, inspect files, or submit orders.

The caller must pass the trust-root key ID and secret explicitly. The secret is
used only for HMAC-SHA256 and is never returned or logged. The result is
`BUILT_NOT_ARMED`; a separate governed caller decides whether to pass the grant
to the existing `BtApiStore.configure_ctp_execution_authorization()` and then
arm through the existing public Store contract.

Stage A/B identity, query IDs, bundle scope, all three PASS gates, expiry, and
all required SHA-256 values are validated fail-closed. The summary is redacted
and contains only hashes, scope, expiry, status, and gate metadata.
