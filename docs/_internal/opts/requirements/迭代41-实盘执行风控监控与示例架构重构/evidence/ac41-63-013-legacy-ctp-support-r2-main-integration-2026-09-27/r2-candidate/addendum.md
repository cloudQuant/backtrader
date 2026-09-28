# Partition 4 r2 candidate addendum

The 013_1/013_2 legacy helper candidate has been rebuilt from the currently hash-verified sources. The four r1 guards remain, and both top-level `load_dotenv_if_available()` calls are removed. The callable helper is preserved for explicit callers.

## Candidate disposition

`CANDIDATE_ONLY / NO_WRITE / LIVE_NO_GO / REVIEW_REQUIRED / NOT_AVAILABLE`. The official per-candidate checklist statuses remain unchanged.

## Verification

- Base source hashes matched both partition entries: `87B59877142447AACB0EEA956AF2F1E5C26024E7BFB71EC38D001FEDC8DBA9CE`.
- Candidate source hashes: 013_1 `E9BFE8EDD8854CEF1184082407BFE5EA2A81268923CBC7A27EB6EAC8F779BE50`; 013_2 `37706DCA228382509581CD76C4D6B938C40E58A5BF6A5F3D44E843C7BBEAECB7`.
- Exact isolated patch replay succeeded and reproduced both candidate hashes. Patch SHA-256: `C859FC66B021D1A734D3A8DB7CE65117B1E0E204DC7415788E368C2B89F57C86`.
- Focused fake test passed 2 tests: all four factory helpers refused before config/constructor access; module imports triggered zero dotenv imports or calls, zero `.env` reads, zero SDK imports, and zero network attempts.
- Existing `tests/unit/test_ctp_pair_examples.py` ran against the isolated overlay: 32 passed, 1 existing deprecation warning. The replay guard recorded zero dotenv/SDK import attempts, zero `.env` reads, and zero network attempts.

## Compatibility and limits

- Imports no longer automatically read project `.env`. Callers that depended on import-time environment loading must explicitly call the still-public `load_dotenv_if_available()` helper.
- This does not establish route closure: `_submit_market` remains and can submit with a broker supplied through custom composition; direct alternate Store/Broker construction sites remain outside this candidate.
- No private config or credential was read; no native SDK, provider, network, order or cancel was used. The candidate was not applied to the main tree.

## Candidate IDs

- `i41-writer-e9aa9f07eb9a0f274802` — `REVIEW_REQUIRED / NOT_AVAILABLE`; `examples/013_2_highfreq_calendar_arbitrage/ctp_example_support.py:492` `self.sell`. Status unchanged.
- `i41-writer-f9e2647652496ba9a609` — `REVIEW_REQUIRED / NOT_AVAILABLE`; `examples/013_1_midfreq_cross_arbitrage/ctp_example_support.py:492` `self.sell`. Status unchanged.
