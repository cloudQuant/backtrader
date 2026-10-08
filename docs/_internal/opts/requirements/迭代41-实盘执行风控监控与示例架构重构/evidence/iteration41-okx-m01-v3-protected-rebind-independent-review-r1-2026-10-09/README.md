# OKX M01 V3 protected metadata rebinder review

**Decision: `GO_ROOT_PROTECTED_METADATA_ONLY`.** This independent review covers only the public rebinder source and its fake Win32 leaf tests. It does not authorize an account or provider invocation, a native API call, an M01 route run, or a formal case result.

The reviewed final pins are:

- `scripts/iteration41_okx_m01_v3_protected_rebind_r1.py`: 26,554 bytes, SHA-256 `772157d54079f3e0900caee75e9be78632084b32a729b15abaee4529e010a296`.
- `tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r1.py`: 25,909 bytes, SHA-256 `4880f722fb9cbaf7cba09d0917a3b6b40f9095fffc1c89abcdfb2ce536e61c46`.

The author supplied a late fix after the first independent run. The initial helper/test pins were 9452b902bbd1056c5366262dcc472e0cc595100600e270354990a5e3ad714127 / 26,452 bytes and 95235eeed082b1687d59cf0cb1f548474a568719d7cea3d89fc788fec5717dc4 / 25,051 bytes; those pins had 13 tests pass and are superseded. The final review and decision bind only the two pins above. The final independent run passed all 14 tests.

The helper checks the fixed new map’s 2,877-byte file digest and exact 19 runtime members, plus the fixed old map digest and R1 admission binding. The R2 review has four direct runtime rows and one separately held test row; that test is not a source-map member. Review JSON and README bytes are also fixed by digest. The late fix maps a backup same-handle readback failure to `protected_write_uncertain`, retains the uncertain handle set, and makes no metadata write.

The fake suite exercises the production `_Win32Leaves` adapter with in-memory Win32/API leaves. It checks handle sharing and identity, ACL checks, hardlink rejection, backup freshness and readback, partial writes, and finite failures. The pinned private API rejects reparse points; the fake suite has no explicit reparse-negative case. No Windows API or protected deployment path was accessed.

Root caller conditions are recorded in `review.json`: retain exact public source and test leases through the call; supply the CUv2 private module with its verified origin; bind the supplied `current_reader` functions and globals to the pinned bytes; establish the fixed target ancestry; check the backup child is absent; and retain the interactive host/context on any uncertain result. The helper itself verifies the reader’s name, origin, constants, and callable presence, but does not bind those in-memory function objects to code/global identity. It also does not verify ACLs on `D:/` or `D:/temp`.

The exact independent test command and isolation details are in `qa-command.txt`. The public packet and prior R2 review identities were rechecked against their frozen hashes. No source or test code was edited, staged, or committed by this review.
