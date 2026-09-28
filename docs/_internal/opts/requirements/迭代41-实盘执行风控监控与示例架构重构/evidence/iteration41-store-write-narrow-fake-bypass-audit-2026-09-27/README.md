# Iteration 41 Store write-path narrow fake audit

Status: `LOCAL_FAKE_AUDIT / CONDITIONAL_BYPASS_REPRODUCED / NOT_AUTHORITY_EVIDENCE`.

This archive preserves two conditional Store-to-injected-API reachability cases against the isolated A028 + frozen generic queue r3 source. It does not authorize a route, prove default CTP write reachability, establish provider acceptance, or show native CTP calls. Both sink surfaces were local fakes.

## Source identity and replay

- Main-tree `backtrader/stores/btapistore.py` at audit time: SHA-256 `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`.
- Frozen r3 patch: SHA-256 `C1550368359A159F18CE6777F6377CCA83DA7F948DE81B99D8DE86BEEE6CCAD3`.
- Isolated patched Store candidate: SHA-256 `00D31700B8554E954C52A748E2DBA09CB781DAED403EEC82AA750D1844513F55`.
- The candidate file is the only copied implementation source. `r3.patch.diff` records the isolated patch; no isolated repository copy is archived.
- `narrow_audit.py` is the replayed harness. Relative to the exact temp-run harness in `narrow_audit-temp-replay.py`, only the repository/source/output path constants were changed to make it runnable from this evidence directory. It loads this candidate Store file while resolving pure-Python support modules from the main repository.
- `results-temp-original.json` preserves the original isolated-run result bytes. `narrow-audit-results.json` is the result from rerunning the archived harness. `run-output.txt` is the archived harness stdout.

## Findings

1. **Mismatched injected direct API**: with Store `provider="binance"`, `backend="direct"`, an explicitly injected fake whose route metadata says `CTP___TEST`, public `submit_order` and `cancel_order_ref` reached fake `ReqOrderInsert` and `ReqOrderAction`. Four fake method calls were recorded. This is a same-process Store/API identity mismatch; it is not the correctly labelled/default CTP route.
2. **Mutable SDK route snapshot**: a fake injected API started with `exchange_kwargs={"BINANCE": {}}`; the Store's constructor-style route snapshot was taken; then the same-process API route mapping was mutated to `CTP___TEST`. `_is_ctp_write_provider()` remained false, `_is_ctp_session_provider()` became true, and `sdk_api` returned the raw fake API. Public submit/cancel accepted fake queue receipts. Manual fake completion through `_execute_sdk_command` reached `async_make_order` and `async_cancel_order`, two fake API sink calls. No worker thread started.
3. **Correctly labelled CTP control**: `provider="ctp"` public submit/cancel both raised the direct-CTP-disabled errors; fake sink call count was zero.

The audit found 22 static sink/call-site candidates. The built-in CTP wrapper's native insert/action methods are unconditional `BtApiStoreError` in this candidate, and direct gateway write methods run their disabled-route guard. Existing generic enqueue/SDK-sink coverage and the separately known managed typed-adapter authority issue were not claimed as new findings.

## Safety and limitations

The harness uses local fake objects and source AST inspection only. It blocks imports under `bt_api_py`, `_ctp`, and CTP native module prefixes; no blocked imports occurred. It does not access credentials, private config, network, provider services, or native SDK code. The queue completions are manually invoked in-process. These results show conditional reachability under injected API mismatch or post-construction mutation; they do not show that a default trusted CTP route accepts or submits a real order/cancel. The official writer dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`; this archive does not close writer audit or establish real SimNow/production support.

## Replay

From the repository root, run:

```powershell
python .\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-store-write-narrow-fake-bypass-audit-2026-09-27\narrow_audit.py
```

The run rewrites `narrow-audit-results.json` and emits the concise JSON summary to stdout. The harness sets `sys.dont_write_bytecode=True` and inserts a meta-path blocker for SDK/native imports.