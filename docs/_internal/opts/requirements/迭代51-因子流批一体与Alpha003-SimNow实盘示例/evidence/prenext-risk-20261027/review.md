# Iteration 51 prenext risk-cancel static review

**Conclusion: GO — `SOURCE_FAKE_PRENEX_RISK_CANCEL_ONLY`.** Static review pins:

- `examples/unified/028_alpha003_simnow_minute/alpha003_strategy.py` — `220330A52A0ACC65427F5C68448E82B80F4EF9FDDDC8C7A75ECEB0BEA4EE3521`
- `tests/integration/test_live_alpha003_history_catchup_execution.py` — `6F25638C7D4B6CF6F133DD97A7C5A6B8E3FDCB2E4DBC3DD871A8B9CF64523881`
- `tests/unit/test_alpha003_simnow_strategy.py` — `81093D0A62FDFCE0A3DEB4ABEA142425BEA39BE3DEB72ACFBAE4BC57BAEB07DC`

Production `prenext` records a complete WARMUP row, then runs live risk maintenance even if tape recording failed, and restores the tape error afterward. `_run_live_prenext_risk` builds from current `_live_facts`, uses their `available_at`, passes no batch, target decision, eligible grid ordinal, or session-close fact, and the risk dispatcher filters plans to CLOSE/CANCEL actions. Replay remains tape-only.

The integration case loads the production strategy through Cerebro with the real cohort/feed, Store, Broker, coordinator, and journal paths. Its subclass seeds one owned OPEN after Store startup and after the first history bar is loaded, immediately before delegating that WARMUP callback to production `prenext`. This validates same-lifetime owned-order cancellation; it does not establish ownership predating history or process-restart recovery. The parameterized durable/failed-tape branches assert no grid decision, no additional OPEN, one risk CANCEL, preserved tape failure, and terminal resolution from refreshed fake-provider query facts. The test calls the real coordinator reconciliation API with that receipt; it does not establish external-provider or account behavior. The only direct state clear removes the synthetic latest quote to make opens unavailable; no journal/ledger state is cleared and no production guard is weakened.

The unit fixture changes derive policy digest/completeness/unqualified fields from the production Alpha003 spec; absent PIT provenance is represented as unqualified. The new binding in the existing prenext tape unit fixture sets `execution_enabled=False` and binds the real risk method, which returns at its normal disabled-execution guard.

Root reports the focused integration run passed 2 cases (`D:\temp\i51-prenext-risk-20261027-r5`) and the unit run passed 4 (`D:\temp\i51-prenext-unit-20261027.xml`); this review did not rerun QA. This is fake-provider source/integration evidence only, not real-account acceptance.
