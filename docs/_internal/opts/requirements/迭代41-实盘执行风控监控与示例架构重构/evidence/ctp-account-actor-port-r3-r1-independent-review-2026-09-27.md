# AccountActorPort r3-r1 independent QA

Date: 2026-09-27

## Decision

**PASS: isolated route-classifier/fake-harness slice only.** **BLOCKED: receipt account/epoch/replay authority and actual main Store integration.** G6-P and LIVE_NO_GO are unchanged. This candidate does not authorize CTP or live execution.

The frozen r3-r1 source at `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1` matched its manifest SHA-256 `417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1`; all 9 manifest entries also matched the independent copy. Its fake-only focus passed 24 tests, exit 0. The raw packet records source/copy verification, exact command/output and adversarial probes.

The specified classifier cases fail closed: unknown custom provider plus `api_cls` is ambiguous; nested `symbol_routes` CTP and nested `exchange_kwargs[OKX].routing.exchange_type=CTP` both classify as CTP; the injected API trap property is not read; explicit CTP cannot be downgraded by an OKX environment selector. The tested direct OKX/Binance, IB_WEB/MT5 gateway aliases, and explicit btapi OKX selectors classify as non-CTP. This is classifier/harness evidence only; public Store compatibility was not executed.

Receipt authority remains blocked: the fake port accepted epoch 1, an actor claiming `acct-other` for configured `acct-configured`, and the same intent twice. Receipt validation checks type and command ID only; there is no expected actor epoch, authenticated account/scope binding, or replay ledger.

## Main source boundary

Static review found no AccountActorPort gate in main `backtrader/stores` or `backtrader_runtime`. `BtApiStore` retains no-adapter submit/cancel legacy paths. Those paths are statically reachable, but **no main Store was instantiated and no main CTP send was run**. Main source SHA-256 values and line anchors are in the raw packet. No source or production code was changed for this evidence.

## Superseded snapshot note

The earlier r3 freeze manifest `A4D336E159AA2C64342F0311710E1B20C55B4B7768F8B23DC03A5525B42F8F9F` and its diagnostic QA at `D:\temp\iteration41-ctp-account-actor-port-r3-qa-independent-20260927` are superseded. It passed 24 tests but missed the deeper nested `exchange_kwargs` CTP selector; r3-r1 adds and passes that case. Do not use the earlier run as current acceptance.

## Artifact hashes

- Frozen candidate manifest SHA-256: `417EBEF0FC2A85B4E37EE22122024B0118211C161795ABB79DAC438840B960A1`
- Independent QA packet manifest SHA-256: `4E2B47493BC6368AFF9A98A302EC651BEA8AFCFF9C0DC70DA36FB382D838CBCE`
- Raw QA archive SHA-256: `524B7B306178F5CAD0AFFEADF3522F108B0D3813F55783C3DF2C1F1D85781CE6`
- Machine record: `ctp-account-actor-port-r3-r1-independent-review-2026-09-27.json`
