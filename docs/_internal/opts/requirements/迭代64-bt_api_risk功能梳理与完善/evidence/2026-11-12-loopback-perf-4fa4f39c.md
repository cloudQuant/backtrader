# Risk service measurements (64.11, INTEGRATION_SIM, loopback)

Machine: platform=macOS-26.5.1-arm64-arm-64bit, machine=arm64, python=3.11.8, cpu_count=8
Load average (1/5/15 min) by phase: {"start": [2.82, 2.85, 2.79], "after_round_trips": [2.54, 2.79, 2.76], "after_claims_1": [2.33, 2.74, 2.75], "after_claims_3": [2.39, 2.75, 2.75], "after_claims_10": [3.52, 2.98, 2.83], "after_restarts": [2.86, 2.92, 2.82], "end": [2.11, 2.61, 2.71]}
Config: {"clients": "round trips and lag: strategy 0 in the measuring process; concurrent claims: one OS process per strategy (own Gateway session and Risk client); a fresh Risk process (same files) before each phase", "instruments": 1, "lag_samples": 5, "orders": 20, "per_client_claims": 2, "reservation_ttl_seconds": 30, "risk_account_day_counters": "disabled", "risk_loop_timeout_ms": 5, "risk_maintain_seconds": 1, "risk_observation_poll_seconds": "0.02", "risk_self_trade": "disabled", "settlement_wait_scope": "after synthetic returns, excluded from reserve/dispatch latencies but affects inter-request intervals", "settlement_wait_seconds": 5.0, "strategies": 10}
Result: INCOMPLETE

| Measurement | n | p50 ms | p99 ms | max ms |
| --- | --- | --- | --- | --- |
| Round trips status: OBSERVED | | | | |
| Direct Gateway reserve | 20 | 14.814 | 25.141 | 25.141 |
| Direct Gateway dispatch | 20 | 8.546 | 12.914 | 12.914 |
| Risk reserve (SDK->Risk->Gateway) | 20 | 41.394 | 167.653 | 167.653 |
| Risk dispatch / claim (SDK->Risk->Gateway) | 20 | 32.345 | 48.323 | 48.323 |
| Claim latency, 1 client processes (13.39 attempts/s, outcomes {'DISPATCHED': 2}, OBSERVED) | 2 | 73.859 | 75.463 | 75.463 |
| Claim latency, 3 client processes (10.74 attempts/s, outcomes {'DISPATCHED': 6}, OBSERVED) | 6 | 273.961 | 287.188 | 287.188 |
| Claim latency, 10 client processes (6.18 attempts/s, outcomes {'DISPATCHED': 20}, OBSERVED) | 20 | 1502.212 | 1732.233 | 1732.233 |
| ORDER filled ingest -> Risk TERMINAL poll (includes synthetic TRADE injection and polling delay) (not observed 0) | 5 | 34.391 | 38.283 | 38.283 |
| Slow disk 20ms: Risk reserve | 20 | 215.591 | 232.587 | 232.587 |
| Slow disk 20ms: Risk dispatch | 20 | 110.184 | 120.828 | 120.828 |
| Slow disk 20ms: claim, 3 client processes (3.57 claims/s, outcomes {'DISPATCHED': 15}) | 15 | 739.627 | 1049.97 | 1049.97 |
| Slow disk 100ms: Risk reserve | 20 | 446.874 | 480.01 | 480.01 |
| Slow disk 100ms: Risk dispatch | 20 | 319.446 | 474.23 | 474.23 |
| Slow disk 100ms: claim, 3 client processes (1.94 claims/s, outcomes {'DISPATCHED': 15}) | 15 | 1558.353 | 2066.667 | 2066.667 |

| Restart | runs (seconds: ready file / status available / observation verified) |
| --- | --- |
| Risk SIGTERM then start | 1.06 / 1.212 / 1.214; 1.083 / 1.229 / 1.231; 1.067 / 1.201 / 1.203 |
| Risk SIGKILL then start | 0.368 / 29.824 / 29.84; 0.334 / 21.193 / 21.209 |
| Gateway stop+start (5 reserved, 5 sent in flight) | Gateway ready 1.016; Risk observation verified after 1.542; first new order dispatched after 2.002 (limit 90) |
| ...then Risk SIGTERM+start | ready file 2.053; observation verified after 0.027; first new order dispatched after 0.183 |
