# AC41-63 Zero-Write Runtime Trace: Independent QA

**Verdict: `NOT_AC41_63_PASS`.** This review validates a route-scoped, instrumented local-backtest trace only. It does not establish writer closure, OS isolation, or acceptance of AC41-63.

## Frozen input and integrity

- Candidate worktree: `C:\Users\yunji\.codex\worktrees\ac41-63-offline-probe\backtrader`; source revision recorded by the candidate: `ad2c142b9a8b42cede85886528c681abdfcb8096`.
- Author evidence: `frozen-input/ac41-63-zero-write-runtime-trace-2026-09-27/`.
- `manifest.json` SHA-256: `f025ca7ca0c0cfa927ff3d7694d581c85ceb1bece56d6ce7abef9242c94e3c7d`; companion `manifest.sha256` matched.
- `evidence.zip` SHA-256: `6ece5cc5f574248f7c488e164b9018a5bed316ff3dbdfdcee25ade10cabdf267`; ZIP CRC check passed and its 12 manifest-listed evidence payloads matched byte-for-byte.
- The author evidence records 4 tests passed, 1 existing pytest configuration warning, no provider modules loaded, no private config or `.env` read, and no CTP/native process.
- Isolated copy builder verified 120 unique manifest/input paths and 109 loaded runtime source hashes against the frozen candidate. It copied 593 source/input files. No private CTP runtime state, `.env`, `.git`, or private config was copied. The copied repo includes only the package-owned local-backtest fixture config.

## Independent execution

The source was copied to `isolated-source/repo/`; all execution below ran there. `PYTHONPATH`, `PYTHONHOME`, installed-backtrader selector, and light-import override were cleared before the test/probe processes; `PYTHONDONTWRITEBYTECODE=1` was set. Pytest plugin autoload was disabled and pytest conftest/config loading was bypassed for the focused command.

Command:

```powershell
C:\anaconda3\python.exe -m pytest -p no:asyncio -p no:cacheprovider --noconftest `
  tests/unit/scripts/test_probe_iteration41_zero_write_path.py `
  tests/unit/runtime/test_iteration41_package_backtest_fixture.py `
  -q --tb=short --basetemp D:\temp\ac41-63-zero-write-independent-qa-20260927\pytest-basetemp
```

Result: **4 passed**, 1 existing warning (`Unknown config option: asyncio_default_fixture_loop_scope`), exit 0, 8.99 s. Raw stdout/stderr/exit files are in `independent-run/`.

The isolated probe also exited 0. It produced `LOCAL_BACKTEST_TRACE_WITH_STUBS`, with the exact package-owned `backtest/local_backtest` fixture running four CSV bars. Its reported inventory has 389 candidates: 327 writer candidates and 62 dynamic-execution candidates; 109 source files loaded; 5 candidate callsites observed; 0 writer callsites observed; 384 candidates unexercised across 145 path groups. `writer_closure_established` is false, and the result's boundary is `CANDIDATE_EVIDENCE_ONLY_NOT_WRITER_CLOSURE`. The route recorded zero network requests, external write requests, provider submissions, or fills.

## Independent guard negative tests

A separate fresh subprocess installed the candidate's exact audit hook and attempted representative Python entry points. `socket.getaddrinfo`, importing `bt_api_ctp`, opening a local file for writing, `os.mkdir`, and `subprocess.Popen` were blocked before their respective side effects; the provider module, file, and directory remained absent. No network lookup or child process was actually initiated.

A deliberate coverage-boundary test created an anonymous pipe before installing the hook, then called `os.write` on its already-open descriptor. The write succeeded (1 byte, read back as `x`) and did not increment the candidate's file-write counter. This is direct evidence that the Python audit/profile hooks are test instrumentation, not OS write isolation or protection against all native/direct syscalls.

## Inventory boundary negative tests

- The frozen inventory contains an unexercised `self.buy` writer candidate at `examples/007_ctp/live_certification/simnow_penetration/cases/T01_open_order.py` (line 101), classified `REVIEW_REQUIRED`; that path was not loaded by the local backtest.
- Adding a synthetic uncovered writer path increased inventory size to 390 and unexercised paths to 385 / 146 groups. It remained `NOT_EXERCISED_NOT_ADMITTED`, and the result remained candidate-only with writer closure false.
- In a separate deliberately weakened inventory, removing the T01 writer entry still allowed the local route to report `LOCAL_BACKTEST_TRACE_WITH_STUBS`. The static source recheck only covers `backtrader_runtime`, `backtrader/brokers`, and `backtrader/stores`; it does not re-scan `examples/`. Therefore inventory edits can hide an out-of-scope example candidate from the route report unless the inventory itself is independently hash-pinned and validated. The underlying frozen inventory remains unchanged; the weakened file exists only in the isolated QA copy.

## Acceptance boundary

This packet independently reproduces the candidate's local fixture trace and its `384/389` unexecuted / `145` path-group accounting. It also demonstrates that representative Python hooks do not constitute a kernel boundary and that the route's restricted source recheck cannot detect a removed `examples/` entry. The candidate itself explicitly reports no writer closure. This is **not** proof that all execution/writer paths are safe, and it is **not** `AC41-63 PASS`.

No private configuration or `.env` was read. No CTP/native module was imported, no provider was started, and no network request, order, or external trading write was made.

## Packet layout

- `frozen-input/`: byte-copy of the author evidence directory.
- `isolated-source/repo/`: isolated source/input copy used for the independent run, including QA-only weakened/augmented inventory files under `evidence/qa-negative/`.
- `independent-run/`: copy-builder, test/probe logs, guard negative probe, and inventory negative setup/results.
- `independent-qa.raw.zip`: archive of the preceding three directories plus this report.
- `packet-manifest.json`: hashes for all archived files and the raw ZIP; manifest is external to the ZIP to avoid self-reference.
