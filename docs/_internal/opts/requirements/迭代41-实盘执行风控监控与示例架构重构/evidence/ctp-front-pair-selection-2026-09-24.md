# CTP SimNow configured-front policy and local reachability observation

Date: 2026-09-24

> **Historical transport record:** the 10:53 UTC preflight below is no longer the latest provider attempt. A later historical pre-I2 read-only preflight entered TD, completed four zero-error queries, then failed strict instrument-row validation and Join shutdown; MD was not reached. It is not current I2 evidence; see [the latest validation summary](validation-summary-2026-09-24.md). The earlier rows below remain time-bounded transport observations only.

## Configured-front policy

The sealed private `config.yaml` is the sole source of SimNow TD/MD addresses. It may contain either one legacy `md_front`/`td_front` pair or an ordered `front_pairs` list with 1–8 exact pair mappings. The forms are mutually exclusive, every pair is unique, and every configured candidate is included in the private config seal. No static official-front allowlist is required for this read-only route.

A single pair is used as configured. With multiple pairs, runtime performs repeated, bounded TCP connect samples against only the configured MD and TD endpoints, before SDK import or credential resolution. The pair score is the larger of the MD and TD median connect RTTs. Runtime selects the lowest score; equal scores retain the original config order. A failed or timed-out endpoint makes its pair incomplete and excludes it. If all pairs fail, runtime rejects before credentials, SDK, or CTP provider access. It never discovers endpoints or falls back outside the configured list. The selected pair remains fixed for the session and its callbacks.

This selection does not inspect time, calendar, TradingDay, set/profile names, or service windows. Trusted code supplies the neutral `provider_environment="simnow"`; endpoint text does not infer `set1` or `set2`. TCP probes carry no account credentials and confer no account, session, market-data, write, or approval authority. Read-only account/session checks, SDK artifact provenance, account-scoped TD/MD responses, zero-write enforcement, and any future write approval remain separate gates. SimNow and any future production CTP operation are intended to use the same physical registered runtime `config.yaml` and shared `ctp:` fields; a future live-mode transition still needs a production runner and independent admission. The old separate production parser/path is legacy/deferred migration evidence, not an independent operator config.

An explicitly invoked config-preparation command can read the root `.env` current pair and complete numbered SET1 / paired SET2 MD/TD inputs, then emit ordered `front_pairs` with set labels removed. Exact duplicate pairs are deduplicated; half-pairs, conflicts, and more than eight candidates are rejected. The current root `.env` has 50 unique keys. This is preparation-time input only: runtime reads only the sealed `config.yaml`, does not inspect `.env` or select by set/time, and never adds endpoints outside the sealed candidate list. The explicit owner-only YAML preparation source also supports `front_pairs`. The latest focused SimNow YAML/multi-source helper contract has `51 passed, 3 skipped`, and the protected output matched at 737 bytes. This verifies input preparation only, not provider use or account access.

## Local observation

An earlier local observation available on 2026-09-24 was one credential-free TCP reachability sample for each endpoint in a single-pair config: MD approximately **379 ms**, TD approximately **1401 ms**. A separate earlier probe in the single-address phase also recorded MD/TD TCP timeouts. These are different point-in-time observations, not a stable availability claim or the later five-pair I2 result.

A later selector run against the then-current single-pair config used a 3-second per-endpoint bound and three connect samples per endpoint. It exited 0 with `reachable_pairs=1`, `selected_index=0`, and pair score **391.38 ms**. Because only one pair was configured, this run did not compare alternatives, resolve a tie, or exercise failed-candidate handling. It is a historical, point-in-time transport observation and shows only that TCP connections were reachable during that run.

## Earlier four-candidate observation (2026-09-24, legacy `ctp_simnow:` schema)

The protected private `config.yaml` was subsequently updated to four unique, paired, unlabeled candidates; the duplicated pair was removed. No endpoint values or set labels are reproduced here. The latest offline `doctor` returned exit 0 and config digest `bfdbe9e31770420097b3829972da9032d0e1a8de456765410992fbf65cee7654`.

One subsequent credential-free selector run, with a 3-second connect bound per endpoint and three samples per endpoint, exited 0 and reported `reachable_pairs=1`, `selected_index=3`, and `score_ms=386.299`. Both MD and TD endpoints for candidate indexes 0, 1, and 2 timed out; both endpoints for index 3 were reachable. This is a historical point-in-time selection observation; the reported score is not a long-run latency or availability guarantee.

The default `preflight` on the same config then exited 2 with `ctp_simnow_preflight_capability_origin_rejected`: the local `bt_api_base` editable/source installation did not pass the SDK origin gate. The SDK wheel pin catalog remains empty and unreviewed. The probe did not read credentials, import the CTP SDK, log into an account, or place/cancel orders. TCP reachability only demonstrates transport connectivity for that run; no real account/session, TD/MD callback, market-data, or trading acceptance is established.

At that time the CLI `doctor` returned exit 0 offline with `next_action=preflight`. The subsequent `preflight` performed the configured-pair TCP probes, then exited 2 with `ctp_simnow_preflight_capability_origin_rejected`: the local `bt_api_base` editable/source installation did not pass the artifact-origin gate. The selector did not read CTP passwords. The origin gate rejected before importing the CTP SDK, resolving credentials, or logging into an account. The SDK artifact pin catalog remains empty.

## Historical later operator observation (2026-09-24; four-pair config)

A later credential-free probe read the same protected four-pair config and sampled each endpoint once with a 2-second connect timeout. The command printed only candidate metadata and the selected score:

```powershell
python -c "from pathlib import Path; import yaml; from backtrader_runtime.ctp_front_pair_probe import select_ctp_front_pair; p=Path('examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml'); pairs=yaml.safe_load(p.read_text(encoding='utf-8'))['ctp_simnow']['front_pairs']; s=select_ctp_front_pair(pairs,timeout_seconds=2.0,max_pairs=8,repeated_samples=1); print({'candidate_count':len(pairs),'selected_config_index':s.config_index,'selected_latency_ms':s.latency_score_ms,'reachable_config_indices':[e.config_index for e in s.evidence if e.reachable]})"
```

It exited 0 and returned `candidate_count=4`, `selected_config_index=3`, `selected_latency_ms=411.9175`, and `reachable_config_indices=[3]`. At that time this superseded the 386.299 ms result as the latest standalone selector observation. It is a single sample at one point in time; it does not establish endpoint stability or account/session access. The command output was captured in the operator transcript, but no durable log or result artifact was retained. A later canonical-schema probe is recorded below and supersedes this as the latest transport observation.

A subsequent `python -m backtrader_runtime.cli preflight --strategy-dir examples/013_3_sa_midfreq_simnow/runtime-ctp-private` used the production three-sample selector and returned exit 2 with `ctp_simnow_preflight_capability_origin_rejected` after candidate probing. No CTP SDK login occurred. The preflight's selected index and score were not captured, so the standalone one-sample result above must not be attributed to that preflight. The `bt_api_base` editable/source installation still fails the artifact-origin gate, and the SDK pin catalog remains empty.

These observations do not prove the remote endpoint's account binding, CTP Trader login, market-data login, subscription acknowledgement, valid tick delivery, TradingDay, account completeness, order/cancel behavior, or trading acceptance. No real account login, order, or cancel acceptance has been completed. They must not be reported as successful SimNow account or trading tests.

## Historical canonical shared-config migration (2026-09-24; four-pair snapshot, not current config)

At that migration checkpoint, the protected config was changed in place from the legacy top-level `ctp_simnow:` block to the canonical shared `ctp:` block. The owner-only Windows ACL and Git-ignore state were retained; mode was `simulation/sandbox`, with four ordered pairs. Offline `doctor` exited 0 with digest `23ffc90a6c481e462f2627a01586e2e90689b916b4acb294503f5c952ec30ea5`; the prior digest `bfdbe9e31770420097b3829972da9032d0e1a8de456765410992fbf65cee7654` is also historical. The current five-pair config and I2 results are in the [latest validation summary](validation-summary-2026-09-24.md).

After migration, an earlier CLI `preflight` probed configured fronts and reached `ctp_simnow_preflight_capability_origin_rejected`; the installed base SDK is editable/source. It did not log into the CTP SDK or perform a real write. A separate standalone one-sample-per-endpoint probe with a 2-second timeout returned `no_configured_front_pair_reachable` and selected no pair. That was a transient standalone observation; the later 10:53 UTC preflight is recorded below. Earlier index-3 observations belong to earlier timepoints and are not contradictory. The earlier preflight's own selected index/score was not captured. Neither result establishes account/session or trading acceptance.

## Historical preflight transport timepoint (about 2026-09-24 10:53 UTC)

A CLI preflight over the same canonical four-candidate config passed its bounded TCP candidate probe and reached the SDK capability-origin gate. The JSON payload reason was `ctp_simnow_preflight_capability_origin_rejected`; it did not report the selected pair or RTT. The PowerShell wrapper returned exit 0 because it did not propagate the native command exit code, so that wrapper status is not the CLI result. At that earlier time no CTP account login/read or write occurred. This is a historical transport observation, not a recorded selector choice, account/session acceptance, or trading result.

