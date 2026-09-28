# Replay instructions

This candidate is bound to the exact raw working-tree preimages in `manifest.json`. It is not a commit and does not authorize a route. Replay it in an isolated checkout/copy; do not use a checkout whose five target-file hashes differ.

1. Verify each `preimage_sha256` value in `manifest.json` against the target repository files.
2. From the repository root run:

   ```powershell
   git -c core.autocrlf=false apply --check --whitespace=error-all D:\temp\ac41-63-injected-broker-failclose-20260927\frozen-candidate-r1\candidate.patch
   git -c core.autocrlf=false apply --whitespace=error-all D:\temp\ac41-63-injected-broker-failclose-20260927\frozen-candidate-r1\candidate.patch
   ```

3. Verify all five resulting raw file hashes against `target_sha256`. The author replay in an isolated exact-base repo matched all five target hashes and changed only the five manifest-listed files. A non-mutating `git apply --check` also passed in the shared tree; no patch was applied there.
4. Verify syntax and focused tests in that isolated checkout:

   ```powershell
   python -m py_compile backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py examples/ctp_options_simnow_live_runner.py tests/unit/test_ctp_options_simnow_live_runner.py tests/unit/test_ctp_options_simnow_mechanical_cycle.py
   ruff check backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py examples/ctp_options_simnow_live_runner.py tests/unit/test_ctp_options_simnow_live_runner.py tests/unit/test_ctp_options_simnow_mechanical_cycle.py
   python -m pytest -p no:asyncio tests/unit/test_ctp_options_simnow_live_runner.py tests/unit/test_ctp_options_simnow_mechanical_cycle.py -q
   ```

5. If optional Iteration 41 source roots are available in the authorized offline QA environment, run `tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py` there. That L2 test is intended to use only its sealed registered fake-provider composition with socket denial; it is not a live SDK or provider test. The author environment lacked those optional roots, so its run skipped before subprocess launch.

The direct forged-auth/descriptor negatives assert that generic runner and cycle APIs reject before buy/sell/cancel attribute lookups or calls. Test-only fake subclasses in unit tests preserve local state-machine coverage and do not represent runtime authority.
