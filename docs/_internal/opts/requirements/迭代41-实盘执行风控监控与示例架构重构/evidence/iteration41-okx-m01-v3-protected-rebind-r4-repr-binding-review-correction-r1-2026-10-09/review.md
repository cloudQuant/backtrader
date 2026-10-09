# R4 generated dataclass repr binding review correction

**Review scope:** narrow static review of the R4 generated `__repr__` binding repair and its source-fake regression test. This corrects the earlier HOLD message, which omitted CPython's post-decoration qualname assignment. It does not replace that historical message or review the full caller for invocation.

## Frozen inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| `.codex-tmp/okx_m01_protected_rebind_r4_root_actual_candidate_20261009.py` | 61,618 | `5efc4f8c02ed09c24cb319fdd2099e719b1772a3a4e0c162fa051edc9427c305` |
| `tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r4_source_fake.py` | 10,085 | `b493fe80b895aa5a153ee8fd37e6c1636cf79029b836a4b9b27e585aa781e2f0` |
| `evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r3-2026-10-09/root-public-dataclass-wrapper-metadata.json` | 307 | `8e8755a60dc72e84fa934edf1a036d439b3a62958987f4736211b77cfc042c0e0` |

## Finding and correction

The R4 helper constructs the expected wrapped repr through `dataclasses._repr_fn`, then sets the expected outer wrapper's `__qualname__` to `<class qualname>.__repr__` before comparing it with the loaded method (`okx_m01_protected_rebind_r4_root_actual_candidate_20261009.py`, lines 502 and 518). At first review I treated that name adjustment as incompatible with the generated function's nested qualname.

That conclusion missed CPython's class-decoration step. In the public `C:/anaconda3/Lib/dataclasses.py`, `_set_qualname` assigns `f"{cls.__qualname__}.{value.__name__}"` to the function (lines 820–824); `_set_new_attribute` calls it (lines 827–834), and `_process_class` installs the repr through `_set_new_attribute` (lines 1045–1047). The generated inner function retains `__create_fn__.<locals>.__repr__`; the stored outer wrapper is renamed to `SocketCloseObservation.__repr__` after `_repr_fn` returns.

The Root-owned bounded public metadata record confirms the same runtime facts: wrapper qualname `SocketCloseObservation.__repr__`, unwrapped inner qualname `__create_fn__.<locals>.__repr__`, and wrapper code from stdlib `dataclasses`. Its scope is `ROOT_READONLY_PUBLIC_DATACLASS_WRAPPER_METADATA`; it records zero metadata-helper invocations and leaves the original status `BLOCKED`.

With that post-decoration step included, the R4 comparison is consistent: it adjusts only the expected outer wrapper metadata, while still binding wrapper code/globals, wrapped-inner identity, inner generated code/globals and qualname, dataclass fields, closure state, defaults, and wrapper attributes. The forged same-globals function in the regression test lacks the expected recursive wrapper and field-generated code, so `bind_module` raises `root_source_binding_failed` (`test_iteration41_okx_m01_v3_protected_rebind_r4_source_fake.py`, lines 246–274). The positive test exercises the exact production binder over the listed public module closure.

## Verdict and limits

**GO for this narrow static repr-binding correction.** The two frozen candidate pins above were rechecked. The author reports the focused test passed 2/2 with one existing asyncio configuration warning; this review did not rerun it. No R4 caller, native/WinAPI operation, provider/account read, or metadata-helper invocation was performed for this review. This is not M01 account acceptance, full-caller invocation approval, or a change to the original blocked result.
