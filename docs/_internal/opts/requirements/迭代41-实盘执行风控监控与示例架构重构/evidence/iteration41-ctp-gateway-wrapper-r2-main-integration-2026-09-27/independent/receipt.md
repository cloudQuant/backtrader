# Independent QA Receipt — Gateway wrapper R2 on Store R5

Verdict: `PASS_NARROW_GUARD_ON_FROZEN_R5_PREIMAGE`.

QA was limited to the immutable candidate at `D:\temp\iteration41-ctp-gateway-wrapper-default-deny-r2-store-r5-20260927`, exact patch replay, AST-extracted wrapper tests, and fake GatewayClient behavior. No main-tree writes, SDK/native imports, credentials/config reads, network, or provider/order I/O were performed.

## Freeze identity

- Manifest SHA-256: `7DE39D43443B35C2A5346E1560AC681640FB9927C9A325052332F3BB2637F230`
- Store R5 preimage SHA-256: `40F776E783388DFA0A5499501E5886744FFD1D74D259E17D3ADECD9A20A5C457`
- Candidate SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`
- Independent replay SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`
- Patch SHA-256: `DCD748DBF2D1041F5B524278F32E2CE696BDC9080980BB3430415D6F1BFF1451`
- Test SHA-256: `7CFB514C466A300A0A47339748F6D0ECF88B2A409B114373A131F2B7B2101BE9`
- Candidate REPORT SHA-256: `A205F85DBFF119F32FFD8F01F477B9F26CE2708BEBEA0D67C6BC9582F1499183`

The current checkout's `backtrader/stores/btapistore.py` is byte-identical to the declared R5 preimage (SHA-256 `40F776E...C457`); it was read only.

## Verification

- Replayed `r2.patch` from the declared source preimage with `core.autocrlf=false`; independent replay matched candidate bytes exactly.
- Ran the six focused tests against the independent replay: all passed. Coverage includes default CTP denial before fake SDK import/client construction, `CTP___…` aliases, Store CTP marker overriding a non-CTP exchange label, unknown/malformed exchange denial, and BINANCE fake delegation.
- Additional fake-only allowlist probes passed direct delegation for BINANCE, IB_WEB, OKX, and MT5 (init/submit/create/cancel calls).
- Store interaction inspected statically and through the AST contract: built-in Store classification is passed to the wrapper marker; CTP classification overrides exchange metadata.

Logs: `focused-tests.log`, `allowlist-probe.log`. Independent replay and probes are under this QA directory; frozen candidate files were not changed.

## Residuals and scope

- Verdict is limited to the direct wrapper guard on this exact Store R5 preimage; it is not end-to-end Store/SDK or provider acceptance.
- `wrapper._client` exposes a raw-client bypass; direct GatewayClient construction and custom Store `api`/`api_cls` injection are outside this patch.
- Same-process Python code can mutate/override wrapper state or methods. This is not a hostile-code boundary.
- CTP read/connect paths may still lazily import/construct a client and connect if called; they were not invoked.
- Non-CTP allowlist compatibility is fake-only and tied to the candidate's static registry reference; future venue additions need review.
- No account-level authorization, production/SimNow acceptance, or writer-closure claim follows from this result.
