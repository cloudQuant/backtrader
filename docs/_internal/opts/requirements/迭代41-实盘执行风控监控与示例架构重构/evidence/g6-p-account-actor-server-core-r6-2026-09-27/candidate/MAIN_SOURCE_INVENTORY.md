# Main-source inventory used for candidate r3

This inventory is read-only evidence from `D:\source_code\backtrader` on 2026-09-27. The r3 candidate does not modify those files.

## Source facts

- `backtrader/stores/btapistore.py:365-366` defines placeholders `futu`, `oanda`, `vc` and named gateway providers `gateway`, `ctp_gateway`, `mt5_gateway`.
- `backtrader/stores/btapistore.py:3430-3432` additionally recognizes every selector ending in `_gateway`; r3 intentionally refuses to infer safety from arbitrary suffixes.
- `backtrader/stores/btapistore.py:1761-1775` resolves CTP and gateway wrappers, while arbitrary other provider values resolve the generic BtApi client path.
- `backtrader/stores/btapistore.py:3435-3450` resolves direct/gateway/forwarding backend names; omitted backend is selected from provider.
- `backtrader/stores/btapistore.py:3768-3773` permits environment provider selection, including for a requested CTP route; r3 treats the raw requested CTP selector as authoritative and never lets this downgrade it.
- `backtrader/stores/btapistore.py:3774-3800` applies gateway environment overrides before connection.
- `backtrader/stores/btapistore.py:16404` rejects placeholder providers when client readiness is reached.
- `backtrader/stores/__init__.py:13` documents `BtApiStore(provider='okx', api=my_bt_api_client)`. R3 rejects injected-client forms because the client cannot be safely classified before inspecting or constructing it; this is a deliberate compatibility break in this candidate.
- `tests/unit/stores/test_btapistore.py:3530-3565` covers `ib_web_gateway`, `mt5_gateway`, and a requested `ctp` overridden by environment provider. R3 preserves explicit non-CTP gateway selectors but deliberately does not permit that CTP environment downgrade.
- `tests/unit/stores/test_btapistore_normalized.py:315-327` and route cases around `1073`, `1167`, and `1269` exercise `btapi` route maps including CTP. R3 recursively inspects nested symbol routes and classifies any CTP selector as CTP.

## SHA-256 of inspected main files

| Path | Bytes | SHA-256 |
|---|---:|---|
| `backtrader/stores/btapistore.py` | 780123 | `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826` |
| `backtrader/stores/__init__.py` | 1275 | `076bb64ae832e189b28b313e0028e24005d507dd6b46d0336fe3295af579b246` |
| `tests/unit/stores/test_btapistore.py` | 133594 | `e7e7b985130f010deed84b920fd0f91712bfe54ac24b5ef8bf1c8fc687bca6b1` |
| `tests/unit/stores/test_btapistore_normalized.py` | 54402 | `84c570a2ea1ddc03a3ae3560e30177cd695b5720bc05225256bc7f6d1016d397` |

The registry is an intentionally narrow candidate set, not an exhaustive statement of every non-CTP provider historically accepted by BtApiStore.
