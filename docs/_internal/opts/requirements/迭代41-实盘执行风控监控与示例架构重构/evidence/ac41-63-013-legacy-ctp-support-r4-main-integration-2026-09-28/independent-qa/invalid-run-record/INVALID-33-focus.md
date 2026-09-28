# Invalid 33-test focus record

**Classification:** `INVALID / EXCLUDED_FROM_ACCEPTANCE`.

Independent QA reported that `tests/unit/test_ctp_pair_examples.py::test_yaml_configs_match_strategy_defaults_and_runners` opened two untracked 013 `config.yaml` files through the generic `load_config()` function. No configuration content was inspected, printed, or copied into this archive. The raw invalid-run log and JUnit are deliberately omitted from the repository archive.

The raw log's SHA-256, retained only as an integrity reference, is `A4491E7788BA3A071073D0F30CBCFBAF6043EA1A04A8CA85D6FA998AA13A8FA6`. This invalid run contributes no test count to acceptance. The safe rerun deselected that test and passed 32 tests; a separate candidate guard passed 1 test.