# SimNow V20 R2 normal source-close source-fake delivery

- Status: READY_FOR_ROOT_STAGE
- Repository: D:/source_code/backtrader, branch dev
- Delivery parent: a95b0287ec9ff318e3e08883bce7216ea0f5b895
- QA execution parent: a95b0287ec9ff318e3e08883bce7216ea0f5b895
- Evidence level: SOURCE_FAKE_NORMAL_SOURCE_CLOSE_ONLY
- Scope: 13 payload paths (helper and fixture, nine exact public evidence archives, manifest, and this record)
- Manifest pin: 26197 bytes / `e0809ae984ff6faee41c3cc3fdb01285a3e7149a9dd1c3f68995fd72f4cef63a`

Root's focused source-fake QA was consumed once at this checkpoint and passed 3/3 with Python exit 0, zero warnings/errors/candidate denials, fourteen guard self-checks, and all 34 public inputs unchanged. The exact raw result, QA harness, source review, outside attester/pre/post snapshots, and aggregate receipt are archived byte-for-byte. Outside pre/post attestations agree on the recorded Git and input metadata.

The source closure contains two new untracked files (the canonical close helper and its three-case fixture) plus 32 tracked, clean inherited public inputs. The original R2 caller, R6 preparation entry, R2 launch, and R3 driver remain inherited `SOURCE_BINDING_DEPENDENCY_NOT_ACTUAL_PREPARATION_ACCEPTANCE`; their pins are recorded in the manifest. Three inherited files have clean CRLF checkout bytes that normalize to the pinned raw HEAD blobs; the exact checkout and raw HEAD pins are recorded.

The tests exercise only a synthetic source lease. No actual preparation, close of retained hosts 1497 or 65851, Gate, provider/account operation, or formal C01 PASS occurred. Root's aggregate says retained-host state was not checked. Historical R1/R2 HOLD evidence remains preserved and excluded.

