# Invalid interrupted broad harness

This run is not valid suite evidence. The harness stubbed the entire `bt_api_py` package, and top-level `pytest.main()` was re-executed by Windows multiprocessing. It stalled at 82% after more than five minutes and showed 164 partial failures before exit `-1`. Do not interpret these 164 as code regressions or treat the partial JUnit/log as a pass/fail suite result. Raw artifacts are preserved for diagnosis only.
