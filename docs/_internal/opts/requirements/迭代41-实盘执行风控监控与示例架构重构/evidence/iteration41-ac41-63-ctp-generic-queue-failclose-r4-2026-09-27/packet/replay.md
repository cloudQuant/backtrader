# R4 isolated CTP generic queue fail-close candidate

Temp-only candidate; no write authorization or writer-closure claim. Active dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`; global posture remains `NO_WRITE / LIVE_NO_GO`.

- Main Store preimage: `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- Candidate Store target: `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE`
- Patch SHA-256: `37EA74FA86D600A5FFC47CBC9511C2215B10765EC791FA9DD6F65036EB867B00`
- Manifest SHA-256: 6EBB6B381D371E429C54FBAF1D884E1FBABF254FDCECE7A0E6F035A1AB462FB6
- Strict replay: `git -c core.autocrlf=false apply --check patch.diff`, then `git -c core.autocrlf=false apply patch.diff` from an exact base checkout. The fresh isolated replay passed and matched all four target files byte-for-byte.
- Candidate affected-module command: `python run_candidate.py`; it preloads and prints `overlay/backtrader/stores/btapistore.py`. Result: 445 passed, 1 skipped.
- Focused static queue contract: `python run_queue_contract.py`; result: 12 passed. `py_compile` and project-config Ruff passed.

Four recovery-exit fake cases cover market_data_only true/false × managed adapter absent/present; all disarm before rejection and reach neither generic queue nor native insert. Typed managed cancellation is preserved from A028.

The classifier uses route/config snapshots, including a snapshot that may fall back to injected API `exchange_kwargs`. This is routing metadata, not authority. The generic sink guard covers `_invoke_sdk_command` only, not the earlier typed managed branch; a stale non-CTP-snapshot / injected-CTP-API fake residual remains unresolved. See `author-report.md` for full limits.
