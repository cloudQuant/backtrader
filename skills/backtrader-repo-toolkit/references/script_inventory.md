# Backtrader `scripts/` inventory and deletion recommendations

Baseline: `D:/source_code/backtrader` @ `cb8493f20` (dev), 2026-11-22. 84 Python files + 6 shell scripts + 2 batch files, excluding `__pycache__` (4.4 MB, gitignored) and `scripts/fixtures/` (60 KB).

All statements are static source inspection plus `--help` smoke tests. No script was executed for real work, and nothing was deleted.

## 1. Bundled in this skill (10 scripts)

Parameterised, no repository-path coupling, standard library only. Every script passes `--help` except `analyze_test_durations.py` (positional log path by design).

| Script | Purpose | `Path(__file__)` / repo coupling |
| --- | --- | --- |
| `analyze_code_lines.py` | Line counts by type/dir | none |
| `analyze_docstrings.py` | Missing docstring / Chinese-comment scan | none |
| `analyze_test_durations.py` | pytest `--durations` summary (no `--help`) | none |
| `clean_markdown.py` | Markdown lint cleanup | none |
| `compare_performance_logs.py` | cProfile log A/B comparison | none |
| `scan_logging_baseline.py` | except/logger/print JSON catalogs | none; unit-tested at `tests/unit/scripts/test_scan_logging_baseline.py` |
| `run_test_with_log.py` | Run a test file, log by git branch | none |
| `clean_a_stock_daily_columns.py` | A-share CSV normalisation (default paths are CLI-overridable) | none |
| `verify_factor_research_pair_semantics.py` | Native/build pair semantics verification | none; unit tests call the repository copy |
| `ci/render_github_ruleset_payload.py` | GitHub ruleset JSON payload renderer | none; unit-tested |

Rejected from bundling after source check (repo-coupled): `profile_performance.py` (`PROJECT_ROOT = dirname(dirname(__file__))`), `profile_factor_examples.py` (inserts ROOT/fincore paths), `run_tests_with_timeout.py` (`os.chdir(Path(__file__).parent)`), `extract_test_data_files.py` (`Path(__file__).parent.parent`), `verify_factor_examples_benchmark.py` (`Path(__file__)`-derived paths).

## 2. Keep in repository — reusable but coupled or heavy

| Script | Why keep |
| --- | --- |
| `aggregate_stock_minute_parquet.py` | pandas/numpy/pyarrow, 898 lines |
| `benchmark_data_loading.py` | pandas; hardcoded `FILES` list but reusable pattern |
| `benchmark_factor_*.py` (6 files) | 769–2363 lines, coupled to `research/` layout |
| `diagnose_factor_research_pipeline.py` | 2350 lines, research-pipeline coupled |
| `verify_factor_examples_benchmark.py` | repo-path derived; tests reference it |
| `verify_factor_research_installed.py` | installed-wheel verification; tests reference it |
| `run_official_backtrader_strategy_regression.py` | repo-specific regression paths |
| `refresh_strategy_durations.py` | actively maintained (commit `de02e78c8`) |
| `extract_test_data_files.py` | stdin-driven, documented in `docs/SLOW_TESTS_TODO.md:425` |
| `inline_regression_tests.py` | **829 generated test files cite it** as provenance — delete would break traceability |
| `verify_iteration41_writer_dispositions.py` | helper `collect_iteration41_writer_inventory.py` missing, but the script itself is论据 |
| `ci/compare_iteration_runtime.py` | unit-tested (`tests/unit/scripts/test_ci_compare_iteration_runtime.py`) |
| `ci/iter60_release_matrix.py` | iteration-bound but release-matrix documentation value |

## 3. CI infrastructure — keep (do not delete)

Actively called by `.github/workflows/`:
- `ci/check_tracked_build_artifacts.py` — `test.yml:46`
- `ci/classify_pr_risk.py` — `pr-governance.yml:92`, `test.yml:388`
- `ci/run_iteration41_cpython38_core_runtime.py` — `test.yml:222`
- `ci/verify_release_wheel.py` — `test.yml:299`

Other CI support: `ci/smoke_iteration41_registered_offline.py` (20-line tombstone marking retired entry; responsibility doc line 430 records the retirement), `ci/run_iteration41_ctp_private_windows_smoke.py` (private-env smoke), `ci/verify_github_governance.py`.

## 4. Shell / batch scripts — keep unless owner signs off

| Script | Role / caveat |
| --- | --- |
| `clean_markdown.sh` | wrapper over `clean_markdown.py`; line 193 calls a missing file `fix_markdownlint.py` — fix before relying on full-tree mode |
| `install_unix.sh` | Unix install helper, referenced in `README.md` |
| `install_win.bat` | Windows counterpart |
| `optimize_code.sh` | pyupgrade/ruff/black/isort driver, referenced in setup guides |
| `pre-push-check.sh` | local quality gate |
| `release.sh` | **dangerous**: `git add`, `git commit`, `git tag`, `git push origin --tags`, `twine upload` (lines 109–140). Keep only with an owner who understands the side effects. |
| `run_tests.sh` | parallel pytest runner; check hardcoded conda/env paths before use |
| `run_tests.bat` | Windows counterpart |

## 5. Delete recommendations

### Group A — one-shot iteration scripts and frozen evidence (38 files + 1 fixture dir)

`iter28_split.py`, `iter28_m0_exports.py`, `iter28_m0_pickle.py`, `iter28_perf_probe.py`, `iter28_pickle_interop.py`, `iter28_pickle_verify.py`, `iter28_spawn_probe.py`, `iter28_verify_moves.py`,
`iteration50_installed_fixture.py`, `iteration51_installed_fixture.py`, `observe_iteration51_process_memory.py`, `validate_iteration51_saved_factor_tape.py`,
`run_iter27_fq3_independent_acceptance.py`, `run_iter27_hf_t1_independent_acceptance.py`, `run_iter27_mf_t1_independent_acceptance.py`,
`run_simnow_c01_native_td_read_v12_root_activation_r1.py`, `run_simnow_c01_native_td_read_v17_root_activation_r1.py`, `run_simnow_c01_native_td_read_v19_root_activation_r1.py`, `run_simnow_c01_native_td_read_v20_root_activation_r1.py`, `run_simnow_c01_native_td_read_v20_root_activation_r2.py`,
`benchmark_iter61_factor.py`, `benchmark_iter61_graph_guard.py`,
`verify_iteration41_external_ai_wheel_interop.py`, `run_iteration41_actor_capacity_benchmark.py`, `run_iteration41_ai_wheel_interop.py`, `run_iteration41_direct_benchmark.py`, `run_iteration41_monitor_benchmark.py`,
`run_iteration50_live_factor_benchmark.py`, `diagnostics/iteration63_latefill_probe.py`, `debug/analyze_okx_min_trading.py`,
`migrate_regression.py`, `flatten_regression_tests.py`, `heal_assertions.py`, `fix_migrated_data_paths.py`, `parametrize_runonce_tests.py`, `select_regression_candidates.py`, `refresh_cross_exchange_local_manifests.py`, `verify_cmp_type_optiontype.py`,
plus `scripts/fixtures/iter27_hf_t1/` and `scripts/regression_migration_selection.json` if their runners are removed.

**Do NOT delete**: `inline_regression_tests.py` (829 generated tests cite it), `verify_iteration41_writer_dispositions.py` (论据 for a frozen gate), `ci/iter60_release_matrix.py` without owner sign-off.

**Caveat**: `repository-responsibilities_zh.md:407/434` says historical certification scripts retain evidence context and that the user already authorised deleting frozen evidence provided consumed calls are not rerun. Cross-check the evidence index in `docs/_internal/opts/requirements/` before deleting.

### Group B — local-environment / credential-bound (5 files)

`reproduce_issue17_from_csv.py` (hardcoded `/tmp/` paths), `setup_mysql_db.py` (hardcoded default DB password), `notify_smoke.py` (DingTalk/Telegram tokens), `notify_smtp_smoke.py` (reads `.env`), `sync_and_test.py` (switches git branches and copies files — destructive in a dirty tree). Move to a private repo rather than deleting if still needed.

## 6. Suggested order

1. Group B (5) — no evidence value, highest safety benefit.
2. Group A one-shot ITER/evidence scripts — archive evidence references first.
3. Group A migration tools — confirm the migration is complete in the tracker.

Never bulk-delete `scripts/ci/`, the shell/batch scripts, or the 10 bundled scripts without a separate decision.
