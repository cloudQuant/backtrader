# OKX M01 V3 protected metadata rebind: actual result

This public archive records Root's single bounded metadata rebind/admission release. The original `observation.json` and `host-pre-exit.json` are preserved byte-for-byte. The directory contains exactly seven files including its archive manifest.

Root invoked the metadata operation once on fresh host session `48777` (tool `99b114`). The observation records `METADATA_REBOUND_ADMISSION_VERIFIED` with scope `PROTECTED_METADATA_ADMISSION_RELEASE_ONLY`, a fresh backup, a matching public admission map, released admission/metadata handles, and source-bound reader function/global bindings. Root reported 30 public and 3 software holds; module code and globals were source-bound. Pre-exit assertions found all helper, admission, source, and Job registries empty, and the outer CUv2 postverify/close completed normally. The host then exited normally with code 0 (tool result `e9cec2`).

Root's public driver-code binding precheck (`306f46`) passed before invocation. The accompanying pin manifest is derived from the root driver's literal support pins and the current 20-row source index. It records 30 public path/hash/byte rows plus three software references from driver constants; none of the software payloads was read. `root-rebind.py` is an exact copy of the public `.codex-tmp` driver, which was not executed during this archive task.

No credentials were read, and no C01 helper, account/provider call, WebSocket route, or native-provider operation occurred. This bounded result establishes no formal M01 case pass. The formal M01 pass count remains 0. Retained host `90344` was not touched.

The proposed helper commit scope is documented in sibling `iteration41-okx-m01-v3-protected-rebind-dev-round-r1-2026-10-09/`. The R2 runtime map already accepted at dev HEAD `9de5439cf3daadd42b96915b94e3c9b6e7a0e1cc` remains unchanged. No source QA or actual operation was rerun for this archive.
