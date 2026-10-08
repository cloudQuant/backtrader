# Optional16 R33 Root preparation R2

R2 addresses the source-metadata mismatch observed in Root's first actual preparation attempt. The pinned V4 loader executes the pinned V3 module without a `__cached__` attribute. Call R1 required that attribute and raised `AttributeError`, which its broad fail-closed receipt reduced to `source_binding_or_preparation_failed`.

The additive Call R2 adapter accepts an absent or `None` `__cached__` slot only for the exact pinned V3 module name, path, and SHA-256. V4 still requires an explicitly present `__cached__ = None` slot. All V3/V4 source digests, function code, globals, module state, class descriptors, and retained-scope identity checks remain in place. The adapter and its R2 driver expose finite phase/category/code diagnostics and never include exception text or raw inputs.

## QA

The isolated focus passed 13 tests with no failures or skips. It used the approved source QA interpreter, `-I -S -B -X utf8`, disabled pytest plugin autoload, cleared `PYTHONPATH`, and used a unique repository-local basetemp. One existing warning reported the unknown `asyncio_default_fixture_loop_scope` config option.

The tests execute the pinned V4 module's nested V3 loader, confirm V3's absent cache slot binds to exact source bytes, reject a non-None V3 slot, preserve strict V4 metadata and V3 global checks, and exercise the V4 fake-handle source read API over only the two public V3/V4 source files. The call adapter still rejects test-only/unopened scopes before calling R1. No external `.pyc` or opaque payload was read or fabricated.

## Limits

This packet is sourcefake-only. It does not create a Root production scope or exercise Entry R2 full-map derivation, V4/R29 profiler verification, the R5/R27 transforms, installer, worker, child, provider, SDK, native code, or account acceptance. The fixed profiler proof depends on opaque bytes and remains a Root-held production gate. The existing R1 source/helper/validator bytes and the R1 evidence packet remain unchanged.

Candidate pins, inherited closure, safe Root metadata reference, and exact QA command are recorded in `source-index.json` and `qa-summary.json`. The ZIP contains only the four new R2 helper/test source files. `checkpoint.json` binds the candidate and packet metadata after archive creation.