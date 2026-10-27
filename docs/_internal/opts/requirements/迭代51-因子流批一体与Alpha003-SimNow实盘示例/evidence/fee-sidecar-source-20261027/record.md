# Iteration 51 fee sidecar source-fake delivery draft

Status: `DRAFT_FOR_ROOT_REVIEW`. This packet is for review and reproducibility; it changes no tracked delivery plan, stages nothing, and commits nothing.

## Scope and current pins

Repository: `D:/source_code/backtrader`, existing branch `dev`; HEAD at the measured freeze was `650947ea74257a577b31f26e4b86d4bb6b705d45`. Evidence level: **SOURCE_FAKE_COMPONENT_ONLY**. The exact nine source/test files and their current size/SHA-256 pins are listed in `manifest.json` and copied under `sources/`.

The ninth file, `tests/unit/scripts/test_iteration51_installed_fixture.py`, is in this source round. It contains fee sidecar isolation, refresh prioritization, and freshness/snapshot tests. The source bytes are included and pinned with the other eight paths.

## Acceptance evidence and historical boundary

The author’s 342-test focus and Root’s separate five-test focus were run before the margin-`None` guard fix. Their source pins are the pre-fix pins below. They are preserved as historical evidence and **must not be described as testing the final source snapshot**.

| Path | Historical size | Historical SHA-256 |
| --- | ---: | --- |
| `backtrader/stores/btapistore.py` | 890726 | `5fbd018a1730ca79d4faeec07cf922050bbab40a0376d17690960ab23eff807c` |
| `backtrader/stores/factor_execution_facts.py` | 239035 | `31a4366baf38b30689a8c45ea14fcc096cc2a1c8b67de4d623d098c7a161c04a` |
| `backtrader/stores/registered_sim.py` | 157462 | `ab7685b5cd1efe0bbcde0f3270d463f644166bf70bafab118c7ce8cb0be01fd3` |
| `examples/unified/028_alpha003_simnow_minute/alpha003_strategy.py` | 250674 | `5ebce557fec45d953fc135ecd780817a2db995d550183028f51e8c723516d7fc` |
| `examples/unified/028_alpha003_simnow_minute/run.py` | 338052 | `766e538abec446191df55d57ae1ad10914e287d98045fae240d5baad4783f2e7` |
| `tests/unit/scripts/test_iteration51_installed_fixture.py` | 129083 | `92f694d77468b4e6c291cc4feef79633e127f790480a9d97077d0c59996c746b` |
| `tests/unit/stores/test_btapistore.py` | 158121 | `c0a2911aafb5b05a61a134f14e5f35baca75b54800d0958c3d181cd58402d37a` |
| `tests/unit/stores/test_factor_execution_facts.py` | 185562 | `fea7447034d03e3cb1230b203bd24b38d96e6cb2c335c1c635afeb3fc0fff1a6` |
| `tests/unit/test_alpha003_simnow_strategy.py` | 217747 | `6da0519f6dff8f7aa555a297a70b81c55ced1b14e1a3fe74719922b03d95207d` |

Historical author focus: 342 passed, one existing pytest configuration warning. Historical Root focus: these five cases passed, one existing pytest configuration warning:

- `test_ctp_query_record_preserves_commission_applicability_fields`
- `test_blocked_optional_fee_query_leaves_live_core_projection_available`
- `test_ctp_wrapper_forwards_bounded_commission_deadline_through_sdk_rate_limit`
- `test_commission_refresh_prioritizes_live_pair_and_held_fees_within_ttl`
- `test_commission_priority_rejects_switched_or_expired_decision_snapshot`

Both runs used the old `factor_execution_facts.py` and `test_factor_execution_facts.py` pins above.

The final incremental regression is `test_extreme_quote_times_multiplier_overflow_keeps_close_and_cancel_readiness`: author 1/1 passed and Root 1/1 passed. Its extreme-but-individually-valid multiplier and quote operands overflow the bounded derived margin product. Projection leaves both margin facts unavailable and reports the existing OPEN blockers, while retaining `risk_reduction_ready=True`, `order_cancel_ready=True`, and `open_risk_ready=False`; refresh no longer raises when comparing a `None` margin result. The first author attempt failed because its fixture had not consumed a quote; that fixture-only failure is retained separately and was corrected by calling `_consume_quote(store)` before projection.

Author’s current run used `.codex-tmp/iteration51_fee_margin_overflow_regression_r2_20261027.xml` and the matching stdout file. Root’s independent current run is archived in `qa/root_margin_overflow_current/`; Root reported all eleven Backtrader/SDK pins unchanged before and after. `git diff --check` across the exact nine source paths passed at freeze; index was empty at the last measured freeze. No tests were rerun to prepare this packet.

The independent reviewer returned **GO for the `None`-guard delta only**, as relayed by Root. The exact reviewer report identity/hash has not yet been attached to this draft and must be bound before final delivery.

## SDK binding and evidence level

The SDK source pin is `bt_api_ctp` dev `be716e7664fa5db8230ed2e502e06997853d2910`; its `bt_api_py` parent gitlink is `2eb9a15a11acebe07386155bc3ab98f1d7efd58b`. The corresponding checkout `client.py` hash is `8b344d14cb059292f9a957642627cc0fdb0e9f16b61102d43c349ce31704718f`; the locally exercised native `_ctp.cp311-win_amd64.pyd` hash is `c93497e653ca42ee8bddafbf2ad57675794d099e95cc5aabe54f353e76ab2fea`.

A separate SDK isolated-wheel/native-extension exercise used local fake request and response leaves and reported successful commission query completion. It did not connect to a provider or account and does not establish actual Backtrader-to-installed-wheel composition. Its report supplied a wheel-digest string with only 57 hexadecimal characters, so that value is not bound here as a valid SHA-256. The native extension is separately pinned above. Another wheel build from `be716` was reported as `0d2c43c993cf489be26e9b4c21910b42f9843f0f975faf5330428991d6b2288f`; that artifact was built but not installed in the wheel-preparation report. This source/fake packet is not an installed Backtrader wheel acceptance.

## Remaining limits

- Pair fee prefetch before the durable grid decision is not accepted. A pair can be durably blocked before its sidecar refresh arrives; do not claim live OPEN liveness or a complete live trading loop.
- CTP header declares `TThostFtdcPriceType` as `double`; callback ingress maps best bid/ask fields to Python `float`, Store retains float, and quote projection applies `Decimal(str(value))`. No inspected public source proves that shortest-decimal conversion is the exchange’s normative tick-decimal economic price or a rigorous upward bound. The fee/risk package therefore does not claim exact-binary upper-bound semantics for quote prices.
- Dynamic fees do not prove a full holding-period cost bound across trading days unless a valid price/fee cap exists. Unbounded monetary-rate exposure must continue to fail closed for OPEN.
- The existing core account projection requires a single account row; multiple same-account currency rows remain a core blocker. Fee-row identity handling does not change that contract.
- The focused CLOSE/CANCEL assertions establish facts readiness only. No actual order, provider, account, or full live acceptance occurred.
- An already-entered synchronous native call cannot be forcibly interrupted, even with bounded query deadlines.

This draft is a public source/fake archive and reproducibility record only; it is not account evidence, a provider acceptance, a live OPEN closure, or a formal Iteration 51 acceptance.
