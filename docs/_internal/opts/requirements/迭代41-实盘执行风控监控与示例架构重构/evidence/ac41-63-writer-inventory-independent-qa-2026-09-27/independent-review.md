# Independent AC41–63 writer-inventory QA

Status: **CANDIDATE_DISCOVERY_ONLY**. This confirms source-scan behavior; it is not writer-closure, runtime reachability, provider, or route-authorization acceptance.

## Frozen inputs

The isolated copy was made after verifying current main-tree hashes against the freeze for the collector (`54AF45DE1C4D14AAF1C3849C9B820F505EDB7A4C34C344B8E4157F490C9E0ED5`), contract test (`C133E3DF976E572EBE2D1017497D10549A0DF7398A88F1B0FFD25E8E80C5ED6E`), surface baseline (`C473B4390D70477978C0EB9673E267244D78A57D0ACB2E8DF6D5F7D3BFA60DD7`), candidates JSON (`FACBBC93067D77A317E3A0ABDE5EF89BC77BD53E4A4EB18722B51124E3E20780`), and disposition JSON (`95116E8866A50D645664764856F1CEB6E855B3D05E540F7E38D59F30EA65C7FD`). Frozen owner report/diff/verification evidence is preserved byte-for-byte under `frozen-owner-evidence/` and its hashes are in `independent-qa-receipt.json`. No source or generated-output file was changed in the main tree. The isolated source manifest is `source-manifest.json` (SHA-256 `423CB56E86375019307D252AD774706A259161D7D4EF7B605410EDB0FC889FC6`).

## Results

- Focused contract suite: **12 passed, 0 failed, 0 skipped**, with the existing warning for the unrecognized `asyncio_default_fixture_loop_scope` pytest option. JUnit: `pytest-junit.xml`; full command output: `pytest-focused.log`. Environment: CPython 3.11.5, pytest 8.2.2.
- Default scan: **349 Python files, 327 writer candidates, 62 dynamic candidates, 0 parse errors**. Coverage: **211 discovered paths, 0 missing baseline paths, 0 unclassified paths**. All **389** disposition entries remain `REVIEW_REQUIRED / NOT_AVAILABLE`.
- The independently generated candidate JSON equals the frozen candidate JSON after excluding only `generated_at`; the frozen `inventory-output-diff.json` after-values were verified.
- Synthetic expansion probe: new nested example directories and a new repository-root `.py` file were reported `UNCLASSIFIED` with `REVIEW_REQUIRED`.
- Synthetic private-state probe: intercepted `Path.read_text`, `Path.open`, built-in `open`, and `io.open` for paths under `runtime-ctp-private`; **zero protected opens** occurred. The synthetic sentinel was absent from scanned paths and serialized output. No actual private config was copied or opened. Forbidden runtime/provider module names (`backtrader`, `_ctp`, `bt_api_py`) were absent from the probe process.
- Ruff 0.16.2 targeted check: clean. CPython 3.12.10 parsed the collector and test with `ast.parse(feature_version=(3, 8))`; no CPython 3.8 interpreter was available.

A first repeat of the synthetic probe hit `FileExistsError` because its fixture directory already existed; the corrected run used a fresh isolated synthetic root and passed. The initial failure log is retained.

## Reproduction commands

```powershell
& 'C:\Users\yunji\AppData\Local\Temp\bt-pytest-asyncio-compat-20260926\Scripts\python.exe' -m pytest -p no:asyncio tests/unit/scripts/test_collect_iteration41_writer_inventory.py tests/unit/scripts/test_verify_iteration41_writer_dispositions.py -vv --tb=short --junitxml='<qa>\pytest-junit.xml'
& 'C:\Users\yunji\AppData\Local\Temp\bt-pytest-asyncio-compat-20260926\Scripts\python.exe' scripts/collect_iteration41_writer_inventory.py --source-root . --output '<qa>\candidate-independent.json'
& 'C:\anaconda3\Scripts\ruff.exe' check scripts/collect_iteration41_writer_inventory.py tests/unit/scripts/test_collect_iteration41_writer_inventory.py
```

See `private-unclassified-probe-rerun.py` for the isolated sentinel and unclassified-path checks. Logs, raw owner evidence, and outputs are listed in `SHA256SUMS.txt`.
