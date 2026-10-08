# Binance TH01 R8 actual: read transport accepted

Root invoked the frozen launcher once after 14 public pins matched and the
R8 independent review returned GO_SOURCE_FAKE_ONLY. The targeted fake regression
passed two tests with the known pytest configuration warning. Root's separate
credential-free real Windows Pipe gate passed all three cases: valid frame/EOF,
second-frame rejection, and missing-EOF rejection. All connections and synthetic
process leaves closed, active workers were zero, and pre/post owner pins matched.
That local gate used no credentials, provider connection or worker process spawn
(tool 099653).

The account invocation returned exit 0 after 7.687 seconds (tool 08d668).
All seven fixed route observations completed; both account schema checks,
pagination_exhaustion and no_silent_truncation were true. First failure and
transport diagnostic were null. The frozen parent returns a route outcome only
after single-frame EOF, zero worker exit, no forced shutdown and successful close.
The agreed first-four-current-state-route read-transport condition is met.

The original observation still records BLOCKED_ACCOUNT_SNAPSHOT,
snapshot_ready=false and full-round acceptance UNACCEPTED. Those fields are
preserved. This accepted component slice does not establish the account trade
universe, complete-account history, three collection phases, actual TradeLogger
ingestion, monitor reconciliation or formal TH01 PASS. The BTCUSDT history read
is a sample. Strict case totals remain unchanged. No late private capture read or
original UNKNOWN-order lookup/retry occurred.

Public readback SHA-256:
e5619c1c3157fd17ca884fef0cecff61a18c75f8b58e175b70aaacbdd37d0117.
Public observation SHA-256:
eb36cfdee9e98fb6167fd4997be1d11e0c69843c29479542ba629332fb1bb1ac.
Owner SHA-256:
290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f.
Launcher SHA-256:
0d6ac6b48540b9fdaf8274d2e303d34e22d095b25ce92bddca23e88281f131ce.

## Delivery gate

The accepted files are in the existing dev checkout. A proposed four-file
commit alone would depend on untracked reader, probe, collector and bootstrap
sources. Delivery is therefore pending an explicit, independently reviewed
dependency closure and selected-source QA. Do not stage unrelated models changes
or historical unaccepted trading paths. No next full-account implementation
round starts before this accepted component is preserved in a scoped dev commit.
