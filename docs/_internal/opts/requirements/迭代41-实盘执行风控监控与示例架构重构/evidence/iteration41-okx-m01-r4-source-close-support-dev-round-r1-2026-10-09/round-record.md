# OKX M01 R4 source-close support round

Date: 2026-10-09. Repository: `D:/source_code/backtrader`. Branch: `dev`.

The R4 actual close was performed at the dev checkpoint `716ca992dd8a05d7d997d25cd667f212eae5bb1c`. Root’s outside-host pre- and post-close attestations both report that HEAD and an empty index. Root later committed the R3 support round; the current delivery baseline supplied by Root is dev `14bde6fbac099f60b7d3b111be72ec14b485555b`, parent `716ca992dd8a05d7d997d25cd667f212eae5bb1c`.

Acceptance level: `ROOT_ACTUAL_NORMAL_SOURCE_CLOSE_ONLY`.

Root invoked the frozen R4 caller once in original host 77310. It returned `BLOCKED / gate_cleanup_not_certain`; the Gate remained `OUTPUT_MISMATCH` with stdout mismatch, so Gate success is false. Root performed the original CUv2 normal exit once. The manager returned `False`, the generator closed, CUv2 normal post-verification checked 31 public and 3 software pins, and the original result, retained row, Gate and five modules remained preserved. Outside-host Git pre/post checks matched, with seven public context pins checked.

This 21-file round packages public support and evidence. Four copied files bind historical source context from the pre-attestation and are fixtures only; no runtime acceptance is implied. The CUv2 snapshot is an inherited committed input and is not duplicated. This proposal does not accept a production runtime change, Gate success, native cleanup, provider/account behavior, formal M01 PASS, or Root host exit. Host 77310 remains alive. The fixed stdout reproduction supports only an inference about Windows newline conversion and does not establish the original child’s output bytes.

The original 17-file proposal is preserved under `.codex-tmp/okx_m01_r4_source_close_support_initial_proposal_r1_20261009/`. No tests were run, no files were staged, and no `.gitattributes` or production runtime source was changed for this proposal. Delivery remains `PROPOSED_PUBLIC_SUPPORT_ONLY` pending Root’s scoped delivery decision.