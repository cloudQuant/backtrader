# Partition 4 r2 independent QA

QA ran in the fresh temporary copy `D:\temp\ac41-63-writer-partition4-candidate-r2-qa-20260927`. The exact supplied patch was copied and applied with `git apply --check` and `git apply`; the resulting source hashes match the candidate manifest.

## Hashes

- Baseline for both support files: `87B59877142447AACB0EEA956AF2F1E5C26024E7BFB71EC38D001FEDC8DBA9CE`
- 013_1 patched `ctp_example_support.py`: `E9BFE8EDD8854CEF1184082407BFE5EA2A81268923CBC7A27EB6EAC8F779BE50`
- 013_2 patched `ctp_example_support.py`: `37706DCA228382509581CD76C4D6B938C40E58A5BF6A5F3D44E843C7BBEAECB7`
- Patch: `C859FC66B021D1A734D3A8DB7CE65117B1E0E204DC7415788E368C2B89F57C86`

## Tests and guards

- Focused fake tests: **2 passed**. Each legacy `create_live_store` / `create_live_broker` helper raises before touching its config/store/broker inputs or constructors. An additional direct import check passed with no fake `dotenv` module preloaded; the supplied focused test also passed its trap-based import check.
- `tests/unit/test_ctp_pair_examples.py`: **32 passed** against the fresh patched overlay.
- `.env` reads, dotenv import/load calls, SDK/native import or library-load attempts, network calls, and non-fixture config reads: **0**. The suite read only the two allowlisted synthetic example YAML files.
- Sensitive environment lookups were intercepted and returned an empty default before consulting the underlying environment (**21 attempts; zero values read**). The replay suite intentionally constructs `BtApiStore` with its local `ReplayClient`; the guard allowed only that exact fixture composition (**21 constructions**), blocked all other Store constructions, and blocked every `BtApiBroker` construction (**0 attempts**).
- `ReplayClient` exposes no order/write methods; replay uses the local `MixBroker`. No external write route, provider session, or real order was exercised.
- The main checkout files remain at the baseline hashes and are clean in `git status`; no main-tree source was edited.

## Verdict and limits

**PASS for the narrow helper/import boundary and local synthetic replay compatibility only.** R2 removes the import-time dotenv invocation while retaining the explicit helper; the four legacy live factory paths fail before config or constructors.

`load_dotenv_if_available()` remains callable, so an explicit caller can still request dotenv loading. The pair strategy's `_submit_market` method remains available to custom broker composition, and other direct writer paths are outside this patch. The candidate remains `CANDIDATE_ONLY / NO_WRITE / LIVE_NO_GO / REVIEW_REQUIRED / NOT_AVAILABLE`; this QA does not establish full writer closure, account authorization, SimNow or production acceptance.
