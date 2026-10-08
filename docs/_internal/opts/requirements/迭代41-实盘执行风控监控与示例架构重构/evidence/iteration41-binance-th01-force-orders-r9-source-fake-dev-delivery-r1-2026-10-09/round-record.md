# Binance TH01 forceOrders transport R9 source-fake component round

Status: SOURCE_FAKE_COMPONENT_ONLY; prepared for exact Root-scoped staging on dev.

## Baseline and scope

- Baseline branch: dev
- Baseline HEAD: 776be6c249b2ba36b9b36c24bb925761be6fc2c2
- Baseline .gitattributes: 48456 bytes, SHA-256 1ca223194884458184fc8a02c3bdbc1828d7b3f527b77201b88d9595ff3920cf. This inventory did not edit it.
- Eight payloads are proposed: the R9 extension, its focused source-fake test, the Root wrapper dependency, three independent-review artifacts, and byte-exact copies of the executed Root QA script and result. The manifest and this record bring the payload count to ten; Root's exact-path .gitattributes rules make eleven proposed files total.
- The source-fake runtime closure is three new files (R9 extension, focused test, Root wrapper) plus three inherited tracked dependencies listed in delivery-manifest.json. Those inherited dependencies are clean at baseline HEAD.

## Verification

- Independent review verdict: GO_COMPONENT_SOURCE_FAKE_ONLY. Its focused suite reported 20 passed, exit 0, with one existing asyncio configuration warning. The review also records py_compile, Black, and Ruff checks.
- Root guarded source QA: 20 passed, exit 0, zero warnings; all eight pre/post source pins matched, module-origin and guard self-checks passed, and the index was empty before and after. The exact executed harness was recovered and archived byte-for-byte. The later unexecuted draft is excluded.
- Root QA's R8 extension and test pins are preservation context only. R8 remains HOLD and is excluded from payload and inherited runtime dependencies. The separate wrapper test is also excluded.

## Scope limits

- The fake exercises pinned wrapper setup, R9 binding, and postflight before a fixed fake stop. It does not issue a forceOrders request or run the worker lifecycle.
- No real provider/account operation, actual transport, worker/Pipe lifecycle, account completeness, or formal TH01 acceptance is established. Full TH01 remains BLOCKED_ACCOUNT_SNAPSHOT; formal_th01_pass=false.
- The wrapper is included as a source dependency with integration disabled. This round does not register or activate it.

See delivery-manifest.json for exact paths, sizes, hashes, inherited pins, and proposed exact-path attribute rules.