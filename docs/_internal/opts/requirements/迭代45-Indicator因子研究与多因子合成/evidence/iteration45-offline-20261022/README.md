# Iteration 45 installed-wheel 025/026 native and offline evidence

This archive records the final local synthetic acceptance run for examples `025_factor_single` and `026_factor_multi` on Backtrader `dev` commit `b2697f13b99461f52c79b48ecf3b18ec6de19972`. The installed Backtrader wheel SHA-256 was `d9165b2640a58db9dca7ad80fc0622e261a2f26930dbab3c1ad9df75f2e9be09`; the interpreter was Python 3.11.5 in `D:\temp\iteration45-installed-20261022`, with Backtrader 1.4.0 and fincore 0.5.1.dev0 imported from that environment's `site-packages`.

`inputs/copied_inputs_manifest.json` records all eight copied example files and the support inputs. The eight 025/026 files (strategy, runner, README, config for each example) were rechecked against both their source-checkout and external-copy SHA-256 values; all eight matched the recorded hashes. Native collection used the external copied runners under `D:\temp\iteration45-copy-final-r4-b269-20261022\cases\...` with `python.exe -E -s ... --no-charts`. Both native runs completed with exit 0, zero broker submit/cancel calls, all required outputs present, 22 table artifacts, and evaluation status `PARTIAL`.

Offline reevaluation used the guarded acceptance harness and the runner files resolved from the source checkout by its explicit `--repo-root D:\source_code\backtrader` option. The worker calls the runner's public `main --dataset` CLI. The reports therefore establish **copied-runner native collection plus byte-identical source-checkout CLI offline reevaluation**; they do not claim that the offline subprocess imported its runner from the copied directory. In both modes, Backtrader and fincore module origins resolve to the installed environment. Offline guard counters for `Cerebro.run`, factor construction, `next`, and `once` are all zero.

Both offline aggregate reports are `PASS`, with dataset bytes unchanged, baseline evaluation IDs and all 22 table-file hashes matching for same-config reruns, and distinct IDs for the requested parameter changes. Each run's required-output validation passed with no missing axes. These PASS values describe the local acceptance harness checks. The factor evaluation manifests themselves remain `PARTIAL` and `acceptance_status=NOT_CLAIMED` as designed.

| Example / scenario | Dataset ID | Evaluation ID | Rows | Result |
| --- | --- | --- | ---: | --- |
| 025 native / same config | `f02afbed896382b02d44d64f6304d4d8d86d26da4c8d03a669a998a36d265118` | `0e426473720997ac13c8a1dfade590c8f765beed08fda49457b3fcdb18fbf23f` | 101,932 | baseline ID and table hashes match |
| 025 periods `(1, 10)` | same | `31f7d974cd008645189de854c4caee11825c029710b78866afd7b5ab173e7112` | 82,515 | different ID; required axes pass |
| 026 native / same config | `298c93ed2e3f7d9a16b155ddd164d334a0468117e36e80826b909d7a7afdd284` | `f17d94934dca73a894e3c9a487a6a11078ed66a5ebdd8c14664a0f87b1962c5d` | 1,227,301 | baseline ID and table hashes match |
| 026 periods `(1, 10)` | same | `557ced9561d9c517c5f8789771e304bb085ae1b7446fb3dbcb760d73775ac76c` | 1,007,565 | different ID; required axes pass |
| 026 weights `close_ma: 2` | same | `478eba5fccbe2ac7cf3a1dfd6e7e04f0b4f9563023cb6c4bad2ea0c68f499e32` | 1,227,301 | different ID; required axes pass |

The 025 offline matrix used the reviewed sequential r4 harness with a 900-second per-scenario timeout. The 026 matrix used the separately reviewed r5 scheduling-only harness, with at most two independent scenario workers and a 2,400-second per-scenario timeout. Both aggregate reports have no problems. `parallel_execution_record.md` describes the two entry paths and bounded concurrency; `resource_observations.json` preserves the workload timing and memory sampling limits.

This archive deliberately omits the saved datasets and the large evaluation CSV/JSON tables. The native run manifests and offline aggregate/worker reports retain dataset fingerprints, evaluation identities, required-output results, and table file byte counts and SHA-256 values. The evidence is a fixed synthetic 20-asset / 301-bar scale diagnostic; it is not a real-account result, a large-universe/high-frequency performance pass, or an overall Iteration 45 pass.

The adjacent output-review.md is an independent read-only review of the same reports, accepted by Root. It confirms the scenario IDs, source-versus-copy path distinction, table hashes, and the bounded 026 weight-value change; it ran no acceptance commands.
