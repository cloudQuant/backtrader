# Intermediate test iteration note

The first run after adding the path-hook regression had 34 passed and 1 failed.
The failure was in the new fake test setup: it did not clear `bt_api_ctp` modules
left in `sys.modules` by an earlier test, so the expected path-hook rejection
was preceded by the intentional `sdk_artifact_check_after_import` rejection.
The fixture now clears SDK modules before the check and has its own cached-finder
case. The final rerun is preserved in `focused-pytest.log` and `focused-junit.xml`
with 36 passed, 0 failed, 0 skipped. The first raw stdout was emitted in the
interactive QA session and was not preserved as a separate file.
