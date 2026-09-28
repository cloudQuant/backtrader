# Initial 16-node filter diagnostic

The initial guarded Store command deselected only 16 explicit SDK-import tests. It left the two R4 `test_native_ctp_wrapper_*` tests in scope; their calls to `optional_sdk("bt_api_ctp.ctp.client")` were stopped by the import tripwire. Result: 730 passed, 13 skipped, 16 deselected, 2 guard-blocked failures, exit 1. This is a harness exclusion-list error, not a Store code regression. The two exact IDs are in `blocked-nodeids.txt`; the corrected run excludes all 18 and is preserved separately in `../../final/`.
