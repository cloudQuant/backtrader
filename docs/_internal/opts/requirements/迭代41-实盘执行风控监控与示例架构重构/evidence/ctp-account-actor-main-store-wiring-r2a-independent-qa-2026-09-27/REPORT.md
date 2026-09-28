# Independent QA — BtApiStore AccountActorPort wiring r2a

**Disposition: `CANDIDATE / explicit-CTP construction ordering verified / NO_WRITE`.** This is isolated source and fake-test evidence. It does not accept an external account Actor, F14, G1/G5, a provider session, credentials, native SDK, or a CTP write route.

## Frozen identity and replay

The 679-entry candidate manifest is `identity/candidate-manifest.json`, SHA-256 `5ad9cce0851fbebd9ac07d520919b7a02f793ab99a133cf96e91f58cede405fb`. The frozen parent R2 manifest is `identity/parent-r2-manifest.json`, SHA-256 `5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a`. All 679 declared candidate payload paths, sizes, and hashes matched the independent QA copy.

The patch chain starts from `sources/store-base.py` (exact main Store base SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`), applies `identity/r2-apply.patch` to reach the R2 Store (`sources/store-r2.py`, SHA-256 `a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8`), then applies `identity/r2a-apply.patch` (SHA-256 `7708df2f0923b74e5f95315390580eb417e9ca05cfa4c6fe41422bc410908e99`). Both `git apply --check` and patch application succeeded in an isolated scratch tree. Final Store SHA-256 `18a02f00ec3b2031932284c9e855395c1c70c3e448dbafcd054e4f079048c4d0`, ActorPort SHA-256 `2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3`, candidate test SHA-256 `6b8eab8156f40e5b14403e4063b323386edb3671e9c614c882604e2c02f6ca4b` all match the frozen candidate manifest.

## Test results

Runs used the compatible Python 3.11.5 / pytest 8.2.2 venv, an extracted candidate root, explicit candidate import origins, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`, `-B`, and `-p no:asyncio`. CTP provider variables were unset for test runs. Every run emitted the preserved raw log and JUnit XML in this packet.

| Scope | Result |
|---|---:|
| Explicit environment/order boundary (3 selected node IDs, including parameterization) | 4 passed |
| Candidate boundary + live-dispatch guard | 18 passed |
| Candidate + managed execution adapter + live-dispatch guard | 25 passed |
| Legacy Store/adapter 30-test set on r2a candidate | 9 passed, 21 failed (expected early CTP actor gate; exit 1) |
| Same 30-test set against exact base Store | 30 passed |

The repeated warning is the existing Quandl `DeprecationWarning`; no test result depends on it. The 21 candidate failure nodes exactly match the existing 21-row review (`r1-legacy-delta-audit`): 8 `FAIL_CLOSED_ASSERTION`, 13 `EXTERNAL_ACTOR_MIGRATION`, 0 unmatched. There were no ordinary non-CTP failures in this set. The test-by-test comparison log is `probes/legacy-disposition-comparison.log`; the table source remains [the existing migration review](../ctp-account-actor-main-store-wiring-r1-legacy-delta-audit-2026-09-27/r1-test-delta-migration-review.md).

## Independent access-order probe

`probes/access-order-probe.py` replaced `os.environ` with a trap object and used caller/API/actor/credential/resolver sentinels. Explicit `provider="ctp"` direct, `provider="ctp_gateway"` gateway, `provider="ctp"` forwarding, and nested CTP facts under an OKX forwarding route all rejected as `external account actor unavailable` with zero environment reads and no caller-object, API/API-class, credential-conversion, Actor/context, resolver, SDK, or native access. This verifies the intended early boundary for those explicit/detectable CTP shapes.

For `provider="btapi"`, the controlled environment selectors `BT_STORE_PROVIDER` and `BT_GATEWAY_EXCHANGE_TYPE` are read before classification; ambiguous routing then fails closed as `store route ambiguous`, with no caller API, credential, Actor, resolver, or dispatch side effect. A custom route object remains untraversed (no attribute, iteration, mapping, index, `str`, or `bool` access) and also fails closed; the two route-selector environment names are read. The explicit OKX raw-API positive retained `RouteKind.NON_CTP` and the same API object. After the probe, `bt_api_py`, `_ctp`, and `ctp_wrap` were absent from `sys.modules`.

Thus r2a fixes the explicit CTP environment-read ordering blocker recorded for r2. Environment-based ambiguous `btapi` classification still intentionally consults its route selectors and fails closed. The probe substituted a controlled `os.environ` object and did not consult the process environment or read real credential values. The OKX positive path did query CTP authorization variable names through that trap. No provider, network, SDK, or native code was used.

## Recommendation and limits

R2a is suitable as a hard-closed Store boundary candidate for continued review: explicit CTP shapes fail before reading environment or invoking caller-controlled objects; the tested OKX path remains compatible. The 13 external-Actor cases remain future migrations, and the 8 fail-closed legacy expectations need assertion updates. This does not supply an authenticated Actor or prove production routing. The default CTP route remains unavailable and writes remain disabled.

Ruff was not independently rerun because the isolated QA venv has no `ruff` module; the candidate author's reported Ruff result is not presented as independent verification. No release/wheel or live-provider acceptance is claimed.