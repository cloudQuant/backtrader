# Optional component local wheel evidence

Repository copy of the 2026-09-30 local report. Its referenced JSON sidecars are copied into this directory. The wheels, full command logs and build inputs remain in `D:/temp/optional-component-wheels-20260930-ae3255ed`.

All five current component source snapshots built and installed offline into a fresh isolated CPython 3.11.5 consumer venv. Wheel metadata/version/RECORD and exact source payload checks passed. Installed RECORD and import origins passed. pip check: No broken requirements found.

This establishes installation and source provenance only; it does not establish execution route/provider/live acceptance. No source repository was edited. No provider/native CTP import or trading/network action was performed. Source input hashes remained unchanged after verification.

The bt_api_base 0.15.5 dependency and third-party wheels were reused from D:/temp/ac41-gateway-parent-compatible-consumer-20260928/wheelhouse. They were not rebuilt from current sources. Full installed-artifact URL/version/hash manifest is installed-artifact-manifest.json. All exact commands/exit codes are commands.json; complete outputs are the matching .log files.

| Component | Source HEAD | Existing working-tree state |
| --- | --- | --- |
| bt_api_gateway | 693a3fe1d71ed4feb56be3887b18b659cb80acf0 | clean |
| bt_api_transport_zmq | 43751c7b5fb87054517bf28fc05d0321bbea6496 | clean |
| bt_api_execution | 0450bb1d7c0a068d9e38adb5b9479701f0c47462 | clean |
| bt_api_risk | 50b6061bd9c676d52d922bf382a948d0ab8a8777 | clean |
| bt_api_monitor | cdb714b65f811442dfcea0dd0ecb38bda9d9a8d6 | clean |

## Built wheels

| Wheel | SHA-256 |
| --- | --- |
| bt_api_execution-0.2.0-py3-none-any.whl | 784f701e3cc22289385a18d187567f8976bd650077b7a27682120dcbe0fafbc1 |
| bt_api_gateway-0.1.0-py3-none-any.whl | 8886fa858dc0c85251034492bf3ee9daec4089eae0705779183d56194bc4f8b0 |
| bt_api_monitor-0.1.0-py3-none-any.whl | 918b036df5094ec0724c2471dc01d7ee9bedfcf4fdfcff8d145f19b4bad46a5d |
| bt_api_risk-0.1.0-py3-none-any.whl | e8e3be76291d1319d56b3883227adc871a5561014f7f2d00b9c308aebddbd64b |
| bt_api_transport_zmq-0.1.0-py3-none-any.whl | 7b2d05e5c7edafee9c3e8baa99bc07f7264faae7e1a67eab3898ca44d3269ac4 |

There are no installation blockers for this five-component environment. Gateway, transport, execution and monitor do not export a module __version__; wheel METADATA agrees with source pyproject versions. Risk module __version__ also agrees. No parent bt_api_py or Backtrader package was included in this five-component smoke. Compatibility with parent/provider routes requires separate verification.
