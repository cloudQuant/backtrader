# Narrow static review: reader `_require` binding

Verdict: `GO_REQUIRE_BINDING_FIX_STATIC_ONLY` for the `_require` rebinding defect.

Reviewed the frozen candidate bytes:

- Helper: `scripts/iteration41_okx_m01_v3_protected_rebind_r2.py`, 28,418 bytes, SHA-256 `0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810`.
- Focused fake test: `tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r2.py`, 23,557 bytes, SHA-256 `4268d340cae45dbcf7574c38f98f2546df78f9a7ff82049f0baecad2904b5eea`.
- Candidate README: 4,183 bytes, SHA-256 `f474779d3dda9b88568fc35a6cc2faccff9765fbed9ef23783a0f6fc9b94ca37`.
- Candidate pins: 2,165 bytes, SHA-256 `dad69ff22275926d824b895a60b59995ecd7e8659f223c88d852cb01a6394043`.

The binding check compiles the pinned public reader source and compares the loaded `_require` function's code object with the uniquely indexed `_require` code object from those bytes. It also requires the function to be a normal Python function with the expected module name, the reader module's exact globals dictionary, and no defaults. `_root_inputs` performs this check before invoking reader parsing/validation functions or entering protected I/O.

The regression test replaces `_require` with a different code object while retaining `current_reader.__dict__` as its globals. It expects `reader_binding_mismatch` and asserts that the fake OS recorded no events, no handles remain active, and both old metadata documents are unchanged. This directly covers the mutable-module-dictionary rebinding gap.

This is static review only; no tests or protected operations were run. The result addresses the public reader `_require` binding only. CUv2 private-helper code/source/global binding remains a Root caller/source-hold precondition and is not established by this review or by a `co_filename` check.
