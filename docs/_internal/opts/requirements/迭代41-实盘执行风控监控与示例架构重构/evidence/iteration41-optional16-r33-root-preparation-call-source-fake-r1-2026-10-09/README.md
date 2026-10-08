# Optional16 R33 Root preparation call R1

This packet adds a Root-only call adapter for the frozen R1 preparation
helper. Before calling that helper, the adapter compares the supplied V4
module and its nested V3 module against isolated reference modules compiled
from the exact V3/V4 bytes supplied from the same open Root-held scope. It
checks source-defined functions, method code, globals, module constants,
class descriptors, module metadata, and the exact retained-scope object. The
reference modules are not registered in `sys.modules`.

After source comparison, the adapter checks that the same open scope manifest
contains the exact V3/V4 pins and rereads both files through that scope. It
then loads the pinned R1 helper from the caller-supplied source bytes and calls
its existing preparation entry point. R1 derives the full map and its support
union from Entry R2, invokes V4/R29's three fixed profiler checks, performs the
R5/R27 source transforms, and stops before the worker installer. R1 performs
the ordinary postverify and close. This adapter retains the scope and module
objects on any failure or uncertain close.

## Fixed source and software descriptors

R1 still derives the map; this adapter does not handwrite or shorten it. The
public contracts remain 582 public rows, 5 software rows, and a support union
derived from the exact held source bindings. Entry R2's pinned R19/R5 source
derivation produces these five software rows:

| Role | Fixed path | SHA-256 | Maximum bytes |
|---|---|---|---:|
| Python runtime | `C:\anaconda3\python.exe` | `c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642` | 67,108,864 |
| Python runtime DLL | `C:\anaconda3\python311.dll` | `162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00` | 134,217,728 |
| Profiler source | `C:\anaconda3\Lib\cProfile.py` | `0a97cf92d0e3efd2e08c2f9b0f0fb8e52a2b26978550804d8e59435201f3fa84` | 67,108,864 |
| Profiler source | `C:\anaconda3\Lib\profile.py` | `4d87bdc8b85bf0a9bdee3e9d975a8a1a0c7360cb264fb68c4c48a102e718e3a3` | 67,108,864 |
| Profiler source | `C:\anaconda3\Lib\pstats.py` | `d62d1e6a626ebd92187419bfe075a76997cce26fe99dd4520786d4a82b6ff10c` | 67,108,864 |

The three adjacent `.pyc` files remain opaque and are checked through the
existing V4/R29 held-scope proof. Their public metadata descriptors are:

| Cache row | SHA-256 | Indexed bytes | Scope maximum | Role |
|---|---|---:|---:|---|
| `C:\anaconda3\Lib\__pycache__\cProfile.cpython-311.pyc` | `9d9a26a0e0aefd28a28dcd09bf97fd66072f8d537d18431f609485e16fb206b3` | 9,056 | 16,777,216 | `ROOT_SNAPSHOTTED_FIXED_STDLIB_CACHE_OPAQUE_BYTES` |
| `C:\anaconda3\Lib\__pycache__\profile.cpython-311.pyc` | `97408337b11e2c3b44bfb68c6e1f5e84de2536d4185049fec7038ecefc22a346` | 23,934 | 16,777,216 | `ROOT_SNAPSHOTTED_FIXED_STDLIB_CACHE_OPAQUE_BYTES` |
| `C:\anaconda3\Lib\__pycache__\pstats.cpython-311.pyc` | `8e66b028e50b31e7fbc7de63fcfe77025304aeb63b84e085ce13db784dca77ad` | 41,851 | 16,777,216 | `ROOT_SNAPSHOTTED_FIXED_STDLIB_CACHE_OPAQUE_BYTES` |

V4's fixed source consumers are `D:\temp\iteration41-optional16-r32-root-held-invoke-r3.py`
(SHA-256 `c93a20753db03df0710b86262b3e4a95d9a49ac5c86fe6aad055acfc945f162e`) and
`D:\temp\iteration41-r29-profiler-bytecode-source-proof-r1.py` (SHA-256
`7c7de3f15710f5f1b3fc8047bb35b50454d2ed6e5382bfb4096827dca405a913`). Both are
fixed public-source descriptors in V4; the source scope requires their held
rows before V4's proof method accepts them. V4 additionally caps each cache
proof read at 2 MiB. This packet contains no software binary, `.pyc`, or R29
source payload.

## QA and scope

The isolated sourcefake focus passed **9 tests**, with no failures or skips and
one existing pytest configuration warning. It verifies source binding,
method/global mutation rejection, retained-scope object identity, fixed
metadata descriptors, default-closed behavior, exact R1 source loading, and
call ordering. It does not create a real scope, run V4/R29, read/fabricate
opaque cache bytes, or invoke Entry R2's successful production prefix.

The candidate is a preparation gate only. It creates no claim, control file,
worker, child, SDK/provider call, or activation. A Root-run success would mean
only that the held source preparation and V4/R29 checks completed and the
scope postverified and closed; it would not establish Optional16 activation
or account-matrix acceptance.

Exact source/dependency pins and the final QA command are in
`source-index.json` and `qa-summary.json`. `source-packet.zip` contains only
the new call adapter and its sourcefake test. `checkpoint.json` binds the
packet metadata after archive creation.

## Candidate files

- `scripts/iteration41_optional16_r33_root_preparation_call_r1.py` — 22,428
  bytes, SHA-256 `762cf58ed2d9d4e2eed2c089a967946610ba660854327d7786c63f463ae4ef8e`
- `tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r1_source_fake.py`
  — 9,903 bytes, SHA-256
  `ef2ff7c1995f0e789489f914b42a342581ea1f7c0ea4d3605d7607f690aae7d6`
