# CTP no-Join native gate R2 static delta review

**Verdict: GO for one R2 run; prior host may exit normally after the stated no-API checks.**

R2 `.codex-tmp/i51_ctp_nojoin_native_gate_r2_20261027.py` is 12,392 bytes, SHA-256 `2be081a0eca708452685603ed9c90e318e9aecafecfa2ef10ce296dc194c3776`. Static diff against R1 contains exactly two replacements: the output root changes from the `r1` suffix to `r2`, and the loopback connect timeout changes from 0.5 to 5.0 seconds. Both are bounded and preserve the fresh-output requirement. The probe remains confined to `127.0.0.1:1`; it closes its socket in `finally`. A failed probe raises the existing finite `FIXED_LOOPBACK_FRONT_NOT_CONFIRMED_CLOSED` error before case construction or either API factory. No other lifecycle logic changed.

R1's 0.5-second probe did not retain its original return code. The separate socket-only observation of `ECONNREFUSED` after 2.047 seconds supports timeout sensitivity as a cause, but does not recover R1's return code or prove that cause. Preserve R1 as a preflight failure; do not recast it as a successful API run.

The original preflight-only host may exit normally after Root confirms `GATE_STATE['cases'] == []`, there is no `active_case`, the only retained exception is the finite preflight `RuntimeError`, and no API/SPI/worker reference was created. The probe's socket is already closed by its `finally` path. Since the API factory was never entered, there is no native API custody to retain; do not require indefinite host retention. This verdict concerns only that original preflight-only host and does not authorize exit if R2 or another run creates an API or leaves an uncertain release worker.

Review was static only; no API/native operation or test was run.
