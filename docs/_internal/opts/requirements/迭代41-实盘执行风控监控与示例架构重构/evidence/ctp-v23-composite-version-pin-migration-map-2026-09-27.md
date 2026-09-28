# V23 composite version and pin migration map (2026-09-27)

Status: **read-only planning evidence; release is not accepted**. No source, wheel, production pin, or default CTP route was changed. Machine-readable details and current source hashes are in [the JSON map](ctp-v23-composite-version-pin-migration-map-2026-09-27.json).

## Frozen inputs and identity facts

- Execution V23 r3 is SOURCE-ONLY, 44 payload files / 1,748,219 bytes, manifest SHA-256 `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`. It declares `bt_api_execution 0.2.0`, colliding with an older source identity. It cannot be installed as a distinct accepted artifact under that identity.
- Its V22 base manifest is `8244038ab975f30de6c0ba56c140f033ddd5b5ce5fb3cabc9e60abb7bf24066d`; the V22 composite manifest is `00577665667a33c9a7d62d331c0cad99b0b660790d0b475d0bd8c1b6caa6e2dd`. V22 `store.py` is 813,051 bytes, SHA-256 `1c7edd065b0167d7c50442762f99a29e4972752bd77636eb7052f022dcefecb6`; V23 `store.py` is 843,956 bytes, SHA-256 `677d4edb5e3b768844117c40fc35dc991e9a6ef850cb94fd069e511c130b6328`.
- Risk cancel-resolution source is manifest `B5B066E901E656E3CE42599E0701B731DF16BE742121A43604B58D69E35DED5D`, distribution metadata `0.1.0`; its pyproject SHA-256 is `DB1EB4FEECED90358F2367CED58720C8C367663D8183FAE45F0362BA040FEAAB`. This is a source candidate, not a final composite release.
- Parent R4 frozen source is `D:\temp\iteration41-cancel-control-r4-freeze-r1-20260927`, 154 payloads, manifest SHA-256 `60B020202ED89169E24AFCA30B1B1B16680151A11C6F52C518D0F5BBFA7FAB0D`. It has an independent 73-test offline fake focus, but its payload has no `pyproject.toml`, so it does not establish a distribution version. The final parent input must be a **new immutable combined tree** containing reviewed R4 control and final issuer/control composition; assign package metadata/version only to that combined tree. R4 `_execution_session.py` SHA-256 `81a7fb8f8fd37f580aefb8b059a3d5684be0f2d199d2a30792e94879d26f448d` still checks Execution `0.2.0` at lines 115 and 134.
- The old parent R2 `0.15.5` metadata/manifest are retained in the JSON as superseded history only. Do not use them as the R4 or final combined parent identity.

The V23 independent QA details, limitation statement, raw evidence ZIP and ZIP hash index are in [the V23 review page](ctp-execution-v23-g1-owner-binding-independent-review-2026-09-27.md). Fake owner-attestor tests do not establish OS G1/G5, and no real provider/native route was exercised.

## Minimum coordinated source/pin migration

The final lock should bind each package’s canonical name, exact PEP 440 version, complete sorted source manifest and byte count, pyproject/build metadata hash, merge-input manifests, dependency wheel hashes, built wheel and RECORD hashes, installed metadata/import origin, test/JUnit/log hashes, and schema/migration lineage. If no clean Git commit exists, use `source_commit: null` with the immutable source manifest, evidence reference, and archive SHA; do not label an uncommitted snapshot as a clean commit. Execution V22→V23 provenance must retain the exact `store.py` identities above. A fake attestor is not G1/G5 evidence.

Main-repository exact version gates and fixtures to revisit after final immutable package identities exist:

| Main-repo file | Current relevant lines | Required coordinated update |
| --- | ---: | --- |
| `backtrader_runtime/ctp_i9_candidate_artifact_set.py` | 119–124 | Refresh artifact-set ID/schema, Execution package entry, wheel/source/evidence identity, dependencies and aggregate lock from final artifacts. |
| `backtrader_runtime/ctp_managed_action_scope_resolver.py` | 97, 434 | Update exact Execution metadata gates. |
| `backtrader_runtime/ctp_managed_action_authority.py` | 123, 153 | Update exact Execution version gates before lazy Store imports. |
| `backtrader_runtime/ctp_managed_account_runtime_candidate.py` | 248 | Update exact Execution distribution gate. |
| `backtrader_runtime/ctp_i9_account_session_candidate.py` | 62 | Update exact Execution version gate. |
| `backtrader_runtime/_iteration41_l2_fixture/managed_013_3.py` | 47–49 | Update source-only Execution/risk/monitor version map as needed. |
| `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py` | 53–55 | Update source-only Execution/risk/monitor version map as needed. |
| `tests/integration/test_iteration41_managed_cancellation_composition.py` | 217–219, 814–816 | Refresh exact catalog pins against the final tuple; keep monitor’s identity independent. |
| `tests/unit/runtime/test_ctp_i9_candidate_artifact_set.py` | 35–55 | Update expected exact tuple and derive manifest expectations from the final artifact evidence. |
| `tests/unit/runtime/test_ctp_managed_action_scope_resolver.py` | 14–19 | Refresh optional-source exact version gate; retain wrong-version rejection. |
| `tests/unit/runtime/test_ctp_managed_action_authority.py` | 922–930 | Refresh optional-source exact version gate; retain wrong-version rejection. |
| `tests/unit/runtime/test_iteration41_l2_fixture_package.py` | 85–87, 111–127 | Update expected source package versions and pin objects. |
| `tests/unit/stores/test_ctp_i9_parent_request_builder.py` | 20–25 | Refresh joint Execution/parent source gate only after the merged parent tree and metadata are frozen. |
| `tests/unit/stores/test_ctp_i9_managed_dispatch_bridge.py` | 336–359 | Align selected Execution source metadata and injected getter; this is source-only evidence, not installed-wheel acceptance. |

Parent `_execution_session.py` and its source tests also require an exact Execution version update in the **new combined parent tree**. Keep `backtrader_runtime/ctp_artifact_provenance.py` base `0.15.5` pins unchanged: those name `bt_api_base`, not parent `bt_api_py`. The generic catalog fixtures with constant fake getters, `backtrader-agent` evidence producer versions, and deployment-evidence `producer_version` fields are not these package gates and should not be blanket-edited.

## Version allocation and release blockers

The local scan found no matching reviewed stable tags/pyprojects/final wheels for Execution `0.2.2`, risk `0.1.1`, or parent `0.15.7`; it cannot prove global version allocation. An existing local V22 disposable wheel already uses `bt_api_execution-0.2.2.dev0+v22.8244038ab975` (SHA-256 `BFA0583BE8F97CC62F979B5848D7B798D440789617BF3DEC813BE53641D0702A`). Native-contract selected `0.2.3.dev0+audit.v23.f94b924e1e20` as a **local V23 probe only**; it is manifest-keyed and is not a release allocation or final composite version. The final composite must use distinct probe identities keyed to its own full manifests; retain wrong-version and same-name/same-version/different-hash rejection.

Release remains blocked until V22/V23 plus the final execution source are one frozen, uniquely versioned artifact; risk and parent R4-plus-issuer are each frozen/versioned; parent execution gates and main pins/tests are updated against the same lock; repeated independent source and installed-wheel RECORD/origin verification passes; and the OS G1/G5 and native/provider gates are independently accepted. No actual CTP trade, live session, or release claim follows from this map.
