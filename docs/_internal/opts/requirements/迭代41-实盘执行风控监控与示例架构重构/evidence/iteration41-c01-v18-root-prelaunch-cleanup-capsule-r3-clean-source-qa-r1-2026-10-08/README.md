# C01 V18 Root prelaunch cleanup capsule R3 clean-source QA

This supplemental record reruns the frozen R3 source/fake suite from an isolated tree. The tree contained exactly the nine files in the R3 packet plus a zero-byte pytest.ini; all nine packet copies matched the pinned source bytes. The compact a/b/c/d/e/f/g/p ancestry preserves the test parents[8] root calculation and keeps the longest wrapper path below Windows MAX_PATH.

The isolated suite passed 23 tests, with no failures or warnings. It used the approved QA interpreter with -I -S -B -X utf8, an explicit site-packages path, pytest plugin autoload disabled, and PYTHONPATH removed. The exact command, output, and file pins are recorded here.

This is source/fake QA only. Independent review returned GO_SOURCE_FAKE_ONLY, and the separately authorized same-owner Root cleanup was accepted with normal host exit code 0. No candidate driver/wrapper execution, activation, new activation call, provider/native/network/WinAPI/process operation, or private-input/capture read occurred. Official C01 PASS remains 0.