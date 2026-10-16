# Iteration 10 ARB06 Backtrader group roll-exit client round

- Repository: Backtrader, branch `dev`.
- Base HEAD: `3cbb062b295869b8334da0c5a3ae5c93fc1095eb`.
- Scope:
  - `backtrader/stores/service_execution_group.py`
  - `backtrader/strategy.py`
  - `backtrader/brokers/btapibroker.py`
  - `backtrader/stores/btapistore.py`
  - `tests/unit/stores/test_service_execution_group_roll_exit.py`
  - this record.
- Result: independent static review is `GO_STATIC / BT_ADAPTER_ONLY`. The focused author test passed 13 cases; Ruff and production-file compilation passed. The pytest output was a direct console result, not a separately retained raw log.
- Boundary: this adds a thin client for the existing typed DIM05 roll-exit contract. It does not implement Risk handlers or prove a normal Host path, shared-account close isolation, or formal ARB06 acceptance. The SDK operation allowlist and DIM05 Risk Host path remain prerequisites for that integration.
- Commit: the exact commit hash for this record is reported in the parent task's post-commit update; Git history is authoritative because a commit cannot embed its own object ID.
