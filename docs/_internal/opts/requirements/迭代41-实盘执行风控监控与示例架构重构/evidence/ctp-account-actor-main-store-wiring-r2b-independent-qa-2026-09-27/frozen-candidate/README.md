# BtApiStore AccountActorPort wiring candidate r2b

**Status: `AUTHOR_CANDIDATE / NO_WRITE`.** This isolated candidate is based on frozen r2a. CTP Actor dispatch, local CTP SDK fallback, credential/provider access for CTP, default-route changes, and live writes remain unavailable.

The r2b review adds row-specific fail-closed migration assertions for the 21 former CTP-local-SDK cases, retains non-CTP contracts, and closes a Store-owned gateway-wrapper route-mutation gap using an offline fake. It is not G1/G5/F14 or production acceptance; see [the r2b review](evidence/r2b-qa-report.md) and [21-row migration map](evidence/r2b-old-ctp-21-migration.md).

The immutable r2b inventory is `evidence/r2b-manifest.json` with sidecar `evidence/r2b-manifest.sha256`. The direct main-base merge patch is [r2b-main-base-apply.patch](r2b-main-base-apply.patch); its exact base/replay evidence is [r2b-main-base-patch-replay.txt](evidence/r2b-main-base-patch-replay.txt). The incremental r2a-to-r2b patch and replay are [r2b-apply.patch](r2b-apply.patch) and [r2b-patch-replay-final.txt](evidence/r2b-patch-replay-final.txt).

Preserved r2a review and exact inputs remain in `evidence/qa-report.md`, `evidence/candidate-manifest.json`, `evidence/r2-parent/`, and `input-sources/`. The r2b wrapper negative probe, final focus, exact 30-test set, broader stores/runtime run, Ruff, and compile logs are under `evidence/`.
