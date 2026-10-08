# V18 Root driver R2 actual diagnostic

Root verified the final independently reviewed R2 driver, packet, public readback and fixed interpreter, then executed the driver once. The complete 29-source + 2-software held map passed and the real wrapper was invoked. The wrapper returned `BLOCKED / root_entry_blocked`; no formal C01 PASS is established. Native and provider execution stages remain unobserved because the current entry collapses underlying errors to that fixed reason.

The finite same-call projection reports the outer Job empty, handles closed, readers joined, both streams at EOF and cleanup verified. The Root CUv2 source scope completed postverification and closed, all 31 held rows were accounted for, and retained references were zero. Root separately observed host exit code 0. No late private captures or native receipts were read.

`observation.json` is the original finite public projection plus its pinned run context: 1,587 bytes, SHA-256 `3ebf3f8c71b5dab3d5f83cfe5af6a7fc28defcf3b94e36123dc8f37e264441e3`. The R2 map repair reached actual dispatch; the C01 entry round remains unaccepted. The next fix must reproduce the wrapper-to-entry source binding and preserve sanitized fixed error codes. Frozen R2 artifacts remain unchanged. No failed C01 files were staged or committed.
