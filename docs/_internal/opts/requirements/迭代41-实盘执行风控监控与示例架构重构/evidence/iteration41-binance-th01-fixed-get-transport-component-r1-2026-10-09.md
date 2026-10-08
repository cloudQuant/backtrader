# TH01 fixed-GET transport component R1

Date: 2026-10-09  
Repository: Backtrader `dev`, inspected base `551132d45847cc4d0c4d48f0f6e92da6b88a00ed`  
Status: `GO_COMPONENT_SOURCE_FAKE_ONLY`; scoped transport component accepted. This does not accept TH01 or an account snapshot.

## Accepted component boundary

The candidate component is the byte-frozen Root owner source plus one
standalone transport test. It is internal and unregistered. The owner file
contains a full-TH01 entry function, but that entry is not accepted, invoked,
or registered by this round. No new runtime registration or CLI grant is
included.

The tested owner import compiles the exact pinned bytes and imports only
standard-library modules. The standalone test has no import of the TH01
reader, account-window collector, Demo availability probe, or R3 source
bootstrap. It exercises the production fixed-GET worker and parent functions
with synthetic HTTPS, Process, and Pipe leaves. The fake transport asserts
that the request is a single fixed-path `GET`; it cannot make a network
request.

The owner source also contains the wider TH01 entry function. That function is
outside this component's acceptance. When called directly today, it obtains
the bounded credential context and creates the protected writer before
loading the wider reader/collector/probe sources. This round does not claim
that the full entry checks for missing wider dependencies before credentials
or private storage. The full entry is present in the owner source but remains
unaccepted and unregistered; the launcher and registration are not delivered.

## Root R8 provider-read observation

Root ran the frozen R8 default probe once after verifying its fourteen public
source pins. The process exited 0 in 7.687 seconds. All seven fixed read routes
completed, both account response schemas were accepted, and pagination
exhaustion and no-silent-truncation checks were true. The separate account
coverage predicates remained unresolved, so the public result was
`BLOCKED_ACCOUNT_SNAPSHOT`, `snapshot_ready=false`, and formal TH01 `PASS=false`.
The result does not establish a closed account-wide fill universe, lifetime
history, or any formal case completion. No later private capture was read and
the original UNKNOWN order reference was not queried, retried, or resolved.

| Route | Fixed path | Completed |
|---|---|---:|
| `account_configuration` | `/fapi/v1/accountConfig` | true |
| `account_v2` | `/fapi/v2/account` | true |
| `standard_open_orders` | `/fapi/v1/openOrders` | true |
| `algo_open_orders` | `/fapi/v1/openAlgoOrders` | true |
| `all_orders_in_window` | `/fapi/v1/allOrders` | true |
| `user_trades_in_window` | `/fapi/v1/userTrades` | true |
| `income_in_window` | `/fapi/v1/income` | true |

Root's sanitized public observation and readback are reported under
`iteration41-binance-th01-demo-shape-root-actual-r8-2026-10-09/`:

- Observation SHA-256: `eb36cfdee9e98fb6167fd4997be1d11e0c69843c29479542ba629332fb1bb1ac`
- Readback SHA-256: `e5619c1c3157fd17ca884fef0cecff61a18c75f8b58e175b70aaacbdd37d0117`

The existing R8 source review packet and its four source bytes are preserved
unchanged. Its packet SHA-256 is
`511452d758e7cadda09d31edcba9b54a94e00eda212379add35744e859c7cd6a`.

## Root-owned local Pipe gate

Root ran the production parent against a real, credential-free Windows Pipe
with synthetic process and frame objects. The three cases passed: one valid
frame followed by EOF; rejection of a second frame; and rejection when EOF
readiness was not established. Connections and fake processes closed, and the
active worker list ended empty. The owner SHA-256 matched before and after.
This validates local parent/pipe handling only; it is not evidence of an OS
spawned signed-GET worker.

Root copied the gate script and its transcript-backed finite observation
into the R8 actual evidence directory. The committed copy is
`iteration41-binance-th01-demo-shape-root-actual-r8-2026-10-09/root-real-pipe-gate.py`
(5,542 bytes, SHA-256
`6e89b966d3f072c9606c3638e5998603e6b4e3fe1dc51b3159b00f3480991e20`); the
summary observation SHA-256 is
`a2aff54d9bf47954463e39117cae0f9ab6ee601cb2368e88db776a1f84192d9b` (779
bytes). The observation is a transcript-backed summary, not raw stdout or a
new invocation. No Root gate was run by this agent.

Root's own source-fake gate record is
`iteration41-binance-th01-fixed-get-transport-component-r1-2026-10-09/qa/root-observation.json`
(1,155 bytes; SHA-256 is recorded in `source-pins.json`). It records tool
`8e438e`, 3 passed, exit 0, the known warning, matching owner/test pre/post
pins, and no repeated actual invocation.

## Source-fake and selected-tree QA

The normal checkout focus command was:

```text
python -m pytest -p no:asyncio tests/unit/live_certification/test_binance_th01_fixed_get_transport_component_r1.py -q --tb=short
```

Result: **3 passed**, one existing `asyncio_default_fixture_loop_scope`
configuration warning. The tests cover a valid bounded frame, malformed and
out-of-range frames, an extra frame, uncertain EOF, wait/read errors, uncertain
worker cleanup, and public diagnostic redaction. The actual worker function is
called inline through synthetic HTTPS and fake Process/Pipe leaves; no OS
process, OS Pipe, socket, or network request is created.

A clean selected-source tree at
`%TEMP%\th01-fixed-get-component-selected-source-r2-20261009` contains only:

| File | Bytes | SHA-256 |
|---|---:|---|
| `pytest.ini` | 10 | `578fc1cd12d8d642df8eff41d71d5119626e9f88f21fafadba6b1092ac840a93` |
| `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |
| `tests/unit/live_certification/test_binance_th01_fixed_get_transport_component_r1.py` | 11,117 | `795d418e16480bda858376d1bd514343806c204712a77d1f84aa8c8bd1b4c326` |

With pytest plugin autoload and bytecode writes disabled, the same selected
test returned **3 passed, exit 0, no warnings**. The exact PowerShell setup and
command were:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -I -B -m pytest -c "$env:TEMP\th01-fixed-get-component-selected-source-r2-20261009\pytest.ini" --confcutdir "$env:TEMP\th01-fixed-get-component-selected-source-r2-20261009" -p no:asyncio -p no:cacheprovider "$env:TEMP\th01-fixed-get-component-selected-source-r2-20261009\tests\unit\live_certification\test_binance_th01_fixed_get_transport_component_r1.py" -q --tb=short
```

This demonstrates that the transport component and its tests run without the
wider R3/TH01 source dependencies. It does not test calling the full owner
entry in that tree.

Independent review returned `GO_COMPONENT_SOURCE_FAKE_ONLY` for the exact
owner/test pins above. The review record is
`iteration41-binance-th01-fixed-get-transport-component-r1-independent-review-2026-10-09.md`
(3,387 bytes, SHA-256
`b708d93fefa14cc6865b8520513595c4fe33f08ee7fc341197a68f7f55553f0a`). It
confirms the same repository and selected-tree test results and records the
full-entry limitation above.

## Why the launcher is not in this component commit

The full R8 launcher and reader depend on a pinned R3 source closure. The
bootstrap's `NAMES` tuple contains 39 source members and `digest()` requires
the exact complete set. The currently required aggregate is
`d4ece913aee90282f9bab4f053f778b128936619b230dc70d6018e93d21e21d2`.
Consequently the four R8 owner/launcher/test files alone would not work in a
clean checkout: the reader, collector, probe, and bootstrap are also
untracked, and the R3 bootstrap requires all 39 members.

Current closure inventory:

- **34 untracked members:** 31 `backtrader_runtime/certification_*.py`
  sources named in `NAMES`, plus the case sources `c01_signed_rest_v2.py`,
  `owned_roundtrip_candidate.py`, and `t01_owned_order_window_v1.py`.
- **Two tracked members are modified:**
  `examples/000_live_certification/binance_penetration/_certification/models.py`
  and `examples/000_live_certification/binance_penetration/cases/T01/run.py`.
  The former adds nullable provider-session fields and authentication profile,
  planned-operation/evidence fields, and order side/time-in-force fields. The
  latter changes the T01 runner with isolated R3 entry modes. The closure binds
  each whole file hash; staging selected hunks would change the aggregate.
- **Three tracked members are unchanged:** the R3 CLI, held private helper,
  and T01 strategy. Their SHA-256 values are respectively
  `62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76`,
  `b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd`, and
  `077435103e7c665beaa31db2e1f85f246876801d63026d7e0e97721d6a17bcc89`.

Additional full-route sources outside the 39-member R3 closure are the
untracked `th01_root_readonly.py`, `th01_account_window_collector_r1.py`,
`th01_demo_availability_probe_r1.py`, and `c01_capture.py`. Their current
SHA-256 values are `2b5e055aff27a07c3d28b6499a45ebf1c7546e7a8f0710ea60feb68d2561ca0f`,
`af33e9870725f67a35dcbb92c01c191e8cb88bfc4a7a9938eb6409bf8b4b7cd9`,
`8b249e3d484e4d02f973db71df428690dc24615bd685ae127781f2b94c66c70e`, and
`4122d6a9f53504c0e7338f0319beb1e0403eefa9e2fb2eb1967a547352cc2c24`.
They are deliberately excluded here with the launcher and wider route tests.

## Frozen delivery whitelist

The manifest at
`iteration41-binance-th01-fixed-get-transport-component-r1-2026-10-09/source-pins.json`
contains the exact `files` rows consumed by Root's stage helper. It lists 15
hashed files; the helper separately verifies and adds the manifest itself by
the SHA-256 passed as `--expected-manifest-sha256`. The resulting public
evidence set is:

1. The frozen owner and standalone transport test.
2. The sanitized R8 observation, readback, and invocation README.
3. The copied Root real-Pipe gate script and its transcript-backed summary.
4. The public R8 independent source review and the component independent
   review.
5. The component round record, source pin manifest, and all five component
   QA records (Root observation plus two command/result pairs).

The owner file's full-TH01 entry function remains unaccepted and unregistered.
The R8 launcher, reader, collector, probe, all 39-member R3 source-closure
additions, `models.py`, T01 runner changes, the historical stale R8 packet,
and unrelated dirty files are excluded. No files have been staged or
committed by this agent. The account snapshot-collection round remains after
Root's scoped component commit.

