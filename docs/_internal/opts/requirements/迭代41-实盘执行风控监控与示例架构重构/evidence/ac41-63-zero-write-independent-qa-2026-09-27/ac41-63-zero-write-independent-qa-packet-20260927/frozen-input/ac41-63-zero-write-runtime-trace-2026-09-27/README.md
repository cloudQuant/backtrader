# AC41-63 route-scoped zero-write trace

**Disposition: `LOCAL_BACKTEST_TRACE_WITH_STUBS / NOT_AC41_63_PASS`.** This
artifact is a route-scoped candidate observation. It does not establish writer
closure or AC41-63 acceptance.

The only dispatched route was the package-owned
`backtest/local_backtest` fixture, registered as
`backtrader.iteration41.local_backtest_fixture`. The route consumed four
packaged CSV bars. Its report states zero network requests, external writes,
provider submissions, and fills. The probe also observed zero blocked
network/process/native-provider imports, file writes, filesystem mutations,
protected-input reads, and writer-entry calls.

The trace ran with explicit harness-only environment adjustments. It selected
`BACKTRADER_LIGHT_IMPORT=1`, marked optional native TA-Lib unavailable, and
bound the package's actual `GenericCSVData` implementation to the feed export
required by this fixture. The standard-library `platform._syscmd_ver` helper
was replaced with an empty deterministic result to prevent its Windows process
query if invoked. The final captured run did not invoke that stub. The report
uses `LOCAL_BACKTEST_TRACE_WITH_STUBS` to keep this run distinct from an
unmodified-host result.

`development-audit-event-extract.json` retains sanitized observations from
blocked default-import diagnostics. Those separate diagnostics saw local
`socket.gethostname` queries, opens of the Windows `NUL` device with
`O_RDWR|O_NOINHERIT` (not a persistent file write), and subprocess attempts
from the standard-library Windows version helper and NumPy's optional SVE
check. The audit hook blocked the subprocess attempts before process creation.
These extracts are marked non-final and are not mixed into the final run's
zero-count report; the final report's local-system, null-sink, and process
observation arrays are empty.

## Static/runtime difference

The frozen candidate artifact contains 389 candidates from 349 scanned source
files (327 writer candidates and 62 dynamic execution candidates). A source
rescan of `backtrader_runtime`, `backtrader/brokers`, and `backtrader/stores`
matched the frozen 175-candidate slice exactly, with no added, missing, or
parse-error rows.

The local fixture trace loaded 109 repository Python files and observed five
candidate callsites; none was classified as a writer-entry call. The remaining
384 candidates are grouped in `unexercised-candidate-paths.json` across 145
repository-relative paths. Of those, 347 candidates were in files not loaded
by the fixture and 37 were in loaded files whose candidate callsites were not
invoked. Every row is `NOT_EXERCISED_NOT_ADMITTED`.

The source/runtime observations do not authorize replay, public shadow,
managed replay, CTP sandbox, live routes, or any provider/account path. They do
not claim completeness for dynamic imports, native code, other interpreters,
or OS-level behavior.

## Captured artifacts

- `probe.stdout.jsonl` is the single-line machine report; `probe.stderr.log` is
  the raw stderr capture.
- `probe_iteration41_zero_write_path.py` and
  `test_probe_iteration41_zero_write_path.py` are byte-for-byte source/test
  snapshots matching the hashes in the manifest.
- `static-candidate-inventory.json` is the exact static input named by the
  report SHA-256.
- `unexercised-candidate-paths.json` preserves the complete 384-candidate
  unexercised group separately for review.
- `development-audit-event-extract.json` keeps the non-final blocked-event
  observations separate from the route result.
- `focus-tests.*.log` and `ruff.*.log` preserve the focused verification
  output.
- `manifest.json` binds the report, inputs, code, and verification outputs by
  SHA-256. `manifest.sha256` is the manifest digest sidecar.
- `evidence.zip` is the self-contained archive of this evidence directory;
  its archive digest is reported separately because it cannot be embedded in
  the files it contains.

## Reproduction

From the repository root in PowerShell, run:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
Remove-Item Env:\PYTHONPATH,Env:\PYTHONHOME,Env:\BACKTRADER_LIGHT_IMPORT,Env:\BACKTRADER_USE_INSTALLED -ErrorAction SilentlyContinue
python scripts/probe_iteration41_zero_write_path.py

$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -p no:asyncio -p no:cacheprovider tests/unit/scripts/test_probe_iteration41_zero_write_path.py tests/unit/runtime/test_iteration41_package_backtest_fixture.py -q --tb=short

python -m ruff check scripts/probe_iteration41_zero_write_path.py tests/unit/scripts/test_probe_iteration41_zero_write_path.py
```

The exact final invocation output, interpreter, inputs, and hashes are recorded
in `manifest.json`. The test run had one existing pytest configuration warning
(`asyncio_default_fixture_loop_scope`); all four focused tests passed.
