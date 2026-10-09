# OKX M01 R7 R3 source-scope normal-close support

**Classification:** `SOURCE_SCOPE_NORMAL_CLOSE_ONLY`.

This packet archives the reviewed and completed one-shot normal close of the
public source scope retained by the already-consumed R3 caller. The R3 caller
itself stopped at `BLOCKED / cuv2_source_pin_mismatch` in `source_custody`,
before Gate 0 or M01 modules were loaded. The caller and its source-fake test
are preserved here as historical fixtures; this packet does not accept them
as callable runtime code.

Root's R3 result recorded 31 public source pins and three software pin
descriptors (34 held entries). The `source_count: 0` in the failed caller result
is its early-return default; it does not mean the held map was empty. The
separate source-close observation records all 34 pins rechecked, normal
postverification and close, the generator closed, and the original reference,
result, and retained Python row preserved. It records zero Gate invocations,
no provider/account acceptance, zero formal M01 passes, and no host-exit
permission. No software payload bytes are included in this archive.

The normal-close helper was independently reviewed for this exact consumed
R3 state and Root then invoked it once (tool `f895a7`, host `96892`). The
independent review authorizes only this pre-gate normal source-scope close. The
original R3 invocation result remains blocked and unchanged. Neither event
establishes child cleanup, host exit, Gate behavior, provider/account behavior,
or a formal M01 pass. Any R4 close is separate evidence and is outside this
packet's scope.

The copied caller and test, candidate pin file, source map/index, and CUv2
public snapshot are evidence and reproduction references only. The source map
and index are the reviewed public files from the R1 integration packet. The
CUv2 snapshot includes its public source and metadata index. Their presence
does not approve the R3 caller or duplicate the 31 inherited source files.

The actual R3 caller ran against dev HEAD `a17f6ce6a4a7e2b69b40b6e5c0a56de16e9286dd`.
This evidence archive was prepared later from current dev HEAD
`716ca992dd8a05d7d997d25cd667f212eae5bb1c`. The archive pins both origins in
`archive-manifest.json`; it does not re-run the caller or its helper. Root's
other working-tree changes remain outside this packet.

Formal M01 PASS remains `0`. This is one accepted local source-scope close
support record, not an account or provider acceptance.
