# I9 CTP / execution 0.2.0 artifact-set review (2026-09-26)

Status: `LOCAL_OFFLINE_CANDIDATE / NOT_PINNED / NO_WRITE`. This receipt verifies
one exact offline wheel set and its fake-API bridge tests. It does not establish
SimNow or production CTP behavior, native Join/Release completion, account
readiness, or order/cancel acceptance.

The new audit-only manifest is
`backtrader_runtime/ctp_i9_candidate_artifact_set.py`. It is not imported by
the default runtime registry or managed CTP composition. Manifest ID
`iteration41-simnow-i9-execution-v1`, version `1`, SHA-256
`b7779cc6bca9e6667298001fdd79f2bac53658f1e01bea31500da617f2350044` fixes
the following three wheel archives:

| Distribution | Source identity | Wheel SHA-256 | Embedded `RECORD` SHA-256 | Installed `RECORD` SHA-256 |
| --- | --- | --- | --- | --- |
| `bt_api_base 0.15.5` | I4-reviewed wheel; no source commit recorded in that receipt | `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d` | `db6239c41b62b1f8f88b26160c4ba12a88c02f6d0f7f5b2d22a417be5c495845` | `47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762` |
| `bt_api_ctp 2.0.4+iteration41.i9` | `19349b8abd546aa4f1522fee674611a9a455e36e` | `7148c4cecc8438426f2ddbe1ee0da0e06d6eb5aa0c699ab901f4cf3e42dc6502` | `d9974746bd0f406a54c4d12870ba17cbd192e8ef152f63ac89c8b5f91d9b06f6` | `3b9b791e6d3aee1feede64b45bbe857243e8fc5e3e66ef5285046c48c47afda3` |
| `bt_api_execution 0.2.0` | `60102bfc493ecc4aa889982d5d8b3a1228e02c92` | `352c26db7636868710dbe28ea0583f49db619dd06e3b9c1f258b69fe68e51787` | `d01ab964f1e2313b1a7614508bd5a5738fbeb23bf412df8346800ac9b58d4d72` | `5dacef3ff58630872678fef4d5cac9093ce2433f65bd80fe59bf60c0a06ab6ff` |

The exact wheels were installed offline into a new CPython 3.11.5 venv with
`include-system-site-packages=false`. Runtime dependencies came from a local
wheelhouse, and `pip check` reported no broken requirements. The verifier read
the retained wheel bytes named by each PEP 610 `direct_url.json`, checked each
archive digest and embedded `RECORD`, validated installed `RECORD` entries and
payload hashes, and required each import root to resolve to that venv's
`site-packages`. It accepted all three artifacts. The installed `RECORD`
hashes bind the local wheel paths recorded by that install; the verifier also
checks the archive hashes and installed payloads so a different local install
path can be checked without confusing its generated `direct_url.json` row with
the wheel's embedded `RECORD`. It requires a clean interpreter with all three
target packages absent from `sys.modules` at both entry and exit. This closes
the preloaded-module case where an untrusted module's `__file__` can disagree
with a forged `__spec__.origin`; callers must run the audit before importing
any of the three SDK packages.

The exact execution 0.2.0 bridge node IDs
`test_close_wakes_real_trader_client_poll_and_discards_its_result` and
`test_close_discards_real_sdk_event_dequeued_before_close_wins` passed against
the installed I9 `TraderClient` and fake APIs (`2 passed`, no skips). The
candidate verifier tests passed (`6 passed`), including forged-spec negative
cases for a preloaded package and submodule; Ruff and `py_compile` passed.
The unit test run emitted one existing pytest configuration warning for the
unknown `asyncio_default_fixture_loop_scope` option.

The earlier I9 combined smoke had no PEP 610 base-wheel origin for its base
install. This receipt closes that provenance gap for the candidate set by
re-testing with the independently reviewed I4 base wheel above. The separate
Native Join worktree currently contains an additional source-only CTP change;
this receipt's CTP wheel does not include it. Any future use of that change
requires a newly built and re-reviewed wheel and a new manifest digest.

This artifact set remains an offline candidate. It does not add a `bt_api_py`
managed parent pin, a runtime registration, a default CTP pin, a production
pin, or a write route. No private configuration, credentials, provider, or
account was accessed for this review.
