# Independent V12 R2 Source-Fake Review

Date: 2026-10-08  
Repository snapshot: `D:\source_code\backtrader`, branch `dev`, HEAD `857d5531bbbb1e188dfab7d27737eb61e346e281`.

## Verdict

`SOURCE_FAKE_ONLY_REVIEW: PASS` for the bounded V12 R2 source closure, Root loader wiring, runner pin, and supervisor reconciliation. This is not a provider, native SDK, account, or live-certification result. Official C01 `PASS` remains zero.

## Candidate packet and verified pins

Packet directory: `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v12-job-reconciliation-front-loader-r2-2026-10-08/`.

- `payload-pins.json`: 4,513 bytes, SHA-256 `a9f559f4b81a7ef48c13daf5bc8e2315bd6731949acefbc385bfca4c83b7ba23`.
- `README.md`: 1,049 bytes, SHA-256 `aefe2f58c66430eb6f8e8194c401c4c8ce15a65a77d58fad208ea81a635184e3`.
- `source-payload.zip`: 203,061 bytes, SHA-256 `14b53ffb109df1997b88c9bab2dee80c670ee7a99e3029cfbc2a7a59155f6216`.

All 25 declared workspace payload files matched both their declared byte counts and SHA-256 values. The ZIP contains exactly 25 declared paths, and every member's byte count and SHA-256 match the pin file. The 19-row V12 source manifest closure also matches. The selected paired-front selector remains pinned at SHA-256 `08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb`.

The prior R1 HOLD snapshot's payload-pins SHA-256 (`2c5a777366153001470a83761e0976bf836d49baafac138ea20e9409c54053a6`) and ZIP SHA-256 (`0d041d9f8c0080b08224a1bcf982b2e6ab4fb612ef856963cd8a69d56371ebff`) match the supplied values; its 24 archive members match its pin file.

## Static review

- The Root wrapper pins V7 at `5342176c77bcffdd61fb232012a1f95c3666362433382b3f2986e978ca6291f5`; V7 exposes `VerifiedC01V12SourceBundle` and `verified_c01_v12_sources`, loads the exact V12 issuer SHA `0ad7f3ccc5e58e669046cdea808a57858151839ec7b2b9dade0f013654ebcc97`, verifies the V12 public manifest closure, and yields the active owner/helper bundle. The wrapper checks the exact bundle type, active state, profile ID, issuer SHA, and runner bytes.
- `run_v12.py` pins the V12 issuer SHA above. Root's fixed child command uses that runner with `--live --profile C01_NATIVE_TD_READ_V12`; the runner validates the same issuer digest before dispatch.
- Root admission binds the V12 source closure and current case runner. It derives `configured_front_pair_count` from the selected configuration and enforces 1–8; the schema has the same bounds and fixed no-write, no-market-data, no-native-join scope.
- V3 supervisor retains the single 5-second cleanup deadline. The nonzero-exit reconciliation grace is capped at 0.5 seconds and at half of the cleanup time remaining. It is entered only for an observed exact-integer nonzero exit and a known positive Job count. It waives termination only after rechecking an exact-integer zero count, EOF on both streams, no capture overflow/read failure, and writer completion. Unresolved or persistent state remains conservative; the process-error result cannot create a worker receipt.
- Current V11 manifest rows are 19/19 pin-consistent. V11's V6 loader remains SHA-256 `2b9d99c8ea11ffc71453ca8345e249564fcb482b904ca9149c9c01f14b694a50`. V2 worker/protocol/contract and V11 V2 supervisor pins also match their manifests.

## QA boundary and limitations

The R2 README records 8 focused fake/source tests passed with one existing pytest configuration warning. I did not rerun them: the packet identifies the approved isolated QA conditions but does not provide an exact executable/interpreter path and command, and this review was restricted to source and archive inspection. No actual Root activation, provider, SDK/native, WinAPI, process, network, private config, `.env`, or `D:/temp` access was performed.
