# Independent TH01 fixed-GET transport component review

Date: 2026-10-09  
Verdict: `GO_COMPONENT_SOURCE_FAKE_ONLY`

This verdict is limited to importing the pinned owner module inertly and exercising its fixed-GET worker and parent transport functions with fakes. It does not accept the full TH01 entry, Demo availability, an account snapshot, or formal TH01 completion. I did not call the full entry, read credentials/private inputs, create an OS process or pipe, or access a provider, network, native, or WinAPI surface.

## Reviewed pins

| File | Bytes | SHA-256 |
|---|---:|---|
| `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |
| `tests/unit/live_certification/test_binance_th01_fixed_get_transport_component_r1.py` | 11,117 | `795d418e16480bda858376d1bd514343806c204712a77d1f84aa8c8bd1b4c326` |

The selected-source tree also matched: `pytest.ini` (10 bytes, SHA-256 `578fc1cd12d8d642df8eff41d71d5119626e9f88f21fafadba6b1092ac840a93`), plus exact copies of the two reviewed files above. It contained only those three files.

## Findings

- The test verifies the owner source hash before compiling it into a standalone module. Its import delta contains no `_certification` or `backtrader_runtime` modules, and the test confirms the active worker and probe-receipt lists start empty. The selected tree excludes repository `conftest.py` and wider TH01 source files; pytest plugin autoload and bytecode writes were disabled for that run.
- The transport cases use fake `Process`, `Pipe`, HTTPS connection, socket, response, and SSL context objects. The valid worker case directly invokes the pinned production worker function with synthetic credentials; its request assertion is restricted to a fixed-path `GET`. Parent validation covers one bounded frame plus EOF, malformed/out-of-window frames, second frame, no readiness, wait/read errors, and uncertain worker cleanup. Diagnostic projection checks representative closed labels and excludes synthetic key, secret, and signature text.
- The owner’s diagnostic projection is a six-field fixed enum document. The component test does not invoke the public probe or any wider reader, collector, availability probe, or R3 bootstrap.
- The full `run_root_th01_demo_shape_probe()` entry remains outside this component verdict. Source inspection confirms it obtains the bounded credential context, creates the protected writer, then calls the wider probe path that loads the reader/collector/probe sources. This review does not claim that direct full-entry calls check wider dependencies before credential access or private storage.

## Verification

Repository focus:

```text
python -m pytest -p no:asyncio tests/unit/live_certification/test_binance_th01_fixed_get_transport_component_r1.py -q --tb=short
```

Result: `3 passed`, with the existing unknown pytest option warning `asyncio_default_fixture_loop_scope`.

Clean selected-source focus ran with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `python -I -B`, `--confcutdir` set to the selected root, and `-p no:asyncio -p no:cacheprovider`. Result: `3 passed`, no warnings. The selected root contained only the pinned owner, pinned test, and empty `[pytest]` config. Both runs use fake process/pipe objects and perform no OS process or pipe operations.
