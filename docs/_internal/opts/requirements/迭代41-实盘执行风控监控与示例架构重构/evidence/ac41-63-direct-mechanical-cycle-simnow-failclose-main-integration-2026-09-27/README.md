# AC41-63 direct MechanicalCycle / SimNowLiveRunner fail-close — main integration

**Disposition:** `DIRECT_FAILCLOSE_MAIN_INTEGRATED / LOCAL_REGRESSION_ONLY / NO_WRITE / LIVE_NO_GO`.

The five main-tree files match the frozen candidate r1 target hashes exactly. The narrow change makes generic `MechanicalCycle` and direct `SimNowLiveRunner` writer dispatch fail closed when trusted dispatch evidence is unavailable. Independent fake-only descriptor probes report zero descriptor attribute lookups/calls before rejection. This accepts only that local fail-close boundary; it does not accept a registered provider route, execution authority, writer closure, or any CTP/native write.

## Main-tree verification

The exact three-file lane was rerun against the matching main-tree source with the asyncio plugin disabled and optional source roots absent. Result: **52 passed, 1 skipped, 0 failed**, exit 0, with one existing pytest configuration warning. JUnit, combined stdout/stderr, exit code, command, Ruff output, and py_compile output are retained under `main-run/`. The skip is `tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py`: `bt_api_execution` is unavailable, so the optional integration child did not launch.

Exact command:

```powershell
python -m pytest -p no:asyncio tests/unit/test_ctp_options_simnow_mechanical_cycle.py tests/unit/test_ctp_options_simnow_live_runner.py tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py -q --tb=short -rs --junitxml=<archive>/main-run/pytest.junit.xml
```

Five current source/test hashes equal the candidate manifest target hashes:

| File | SHA-256 |
| --- | --- |
| `backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py` | `573882B80DB8F47F8B7C8CCA8AE2C9C790469EB741C81BB523FC104E7D6C0C33` |
| `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py` | `38696E2C08439C5D471327F22377C65D589EF3BE043A2924F751CBAE9C8BC5EE` |
| `examples/ctp_options_simnow_live_runner.py` | `36B3056B0196D99CB8E24F02D251D96203B9A30DF6193525B50821C46A66384C` |
| `tests/unit/test_ctp_options_simnow_live_runner.py` | `D0F1439FDAD66E18422378BF6F98433105487897ACF4939842CAFB9F4533C774` |
| `tests/unit/test_ctp_options_simnow_mechanical_cycle.py` | `67614A96854400E175EEFC69F1F291914E036160DDBBB80D448365A4AF2189A4` |

Candidate manifest SHA-256: `D0FBC2C38F6BAD8A8778A447FAD4C8F0D5C7C7F34D9348D558DA8B7791749DDA`; independent QA report SHA-256: `DA769EA3FBB3E64FB00E0EE08811AE57D37226B1F5AD5A636223C1E317B01A98`.

## Supplemental broad Store/Runtime regression

After the MechanicalCycle and 013_1/013_2 support main patches, and before Store r5, the corrected broad command was run:

```powershell
python -m pytest -p no:asyncio tests/unit/stores tests/unit/runtime -q --tb=short --junitxml=D:\temp\iteration41-main-broad-after-mechanical-20260927\stores-runtime.junit.xml
```

Pytest summary: **2,641 passed, 43 skipped, 2 xfailed, 0 failed**, one existing `PytestConfigWarning`, 112.27 seconds, exit 0. JUnit records 2,686 cases, 0 failures/errors, and 45 skipped records (including the two xfails). The exact corrected command metadata, JUnit, stdout/stderr, and exit code are in `main-run/store-runtime-broad/`; their hashes are listed in `payload-manifest.json` and `SHA256SUMS.txt`. The initial malformed command attempt (exit 4) is not included; this section records only the corrected passing run.

This broad regression records the Store/Runtime state at that point. It is not a causal attribution to the narrow MechanicalCycle change, and it does not establish provider/native execution, writer closure, or CTP/live acceptance. `NO_WRITE / LIVE_NO_GO` remains.

## Preserved L2 result and limits

The independent reviewer ran the registered fake L2 positive in both candidate and exact-base isolated copies using the same historical fake/local source map. Both failed at the same ambiguous-response assertion: the fake runner expected an `UNKNOWN` state that was not marked. Both direct debug runs recorded zero socket attempts. This is a baseline-reproduced local fake failure, not a candidate regression and not a live/provider attempt. The requested positive **9 submissions / 1 cancellation / 0 external writes remains NOT VERIFIED** for both versions.

The focused fail-close tests and property-descriptor adversarial probe are local API-boundary evidence only. They do not sandbox arbitrary same-process Python subclasses or direct broker calls. No SDK/native module, provider, network, credential, private config, account, or order was used. `NO_WRITE / LIVE_NO_GO` remains.

## Evidence package

`candidate-input/` preserves the exact frozen manifest, patch, and replay instructions; `independent-qa/` preserves the independent report and raw candidate/base logs; `main-source/` contains byte-identical copies of all five integrated files; `main-run/` contains the current main-tree rerun sidecars. `payload-manifest.json` and `SHA256SUMS.txt` bind the copied evidence. The source/evidence ZIP CRC and SHA-256 are recorded in [ZIP-RECEIPT.json](ZIP-RECEIPT.json); [ARCHIVE-RECEIPT.json](ARCHIVE-RECEIPT.json) binds the README and archive controls.
