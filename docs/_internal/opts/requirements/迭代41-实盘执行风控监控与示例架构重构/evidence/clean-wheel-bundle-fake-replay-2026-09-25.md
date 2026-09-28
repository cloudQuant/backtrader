# Frozen-parent clean wheel-only fake/replay smoke

日期：2026-09-25
状态：`LOCAL_FAKE_REPLAY_PASS / CTP_SKIPPED / NO_WRITE`

## Latest official-PyYAML rerun

The 61-wheel manifest (`SHA-256 4b189520d2a5b5b9b83a3d380096b75137beb1eb375937c916ab9a863f535289`) replaces only the first-round locally repacked PyYAML wheel; the other 60 wheel hashes are unchanged. PyYAML 6.0.1 `cp311-win_amd64` was fetched from [the official PyPI file](https://files.pythonhosted.org/packages/b3/34/65bb4b2d7908044963ebf614fe0fdb080773fc7030d7e39c8d3eddcd4257/PyYAML-6.0.1-cp311-cp311-win_amd64.whl). Its SHA-256 is `bf07ee2fef7014951eeb99f56f39c9bb4af143d8aa3c21b1677805985307da34`, matching the [official PyPI JSON digest](https://pypi.org/pypi/PyYAML/6.0.1/json). The wheel RECORD has 24 rows, 23 hashed, and 0 invalid.

A fresh short-path no-system venv passed `pip check`, all nine installed SDK/PyYAML RECORD checks, and SDK/YAML import-origin checks. The frozen parent candidate is commit `af538469…`, wheel SHA-256 prefix `cfa83b1a…`; its independent RECORD and 151 source-member review passed. The CLI smoke exited 0: 14 routes selected, 14 passed, 0 failed, 2 skipped (private CTP and public shadow). Both managed fake L2 replay routes passed, and socket/DNS guard attempts were zero. Provider/account I/O was none; network access was limited to PyPI metadata and downloading the official wheel.

The manifest SHA and wheel smoke evidence are recorded outside the repository at `D:\bt_api_execution_candidate_20260925_clean\offline_clean_bundle\frozen_parent_af538469\official_pyyaml\official_pyyaml_smoke_evidence.json`. This is local fake/replay wheel integration only. CTP was skipped, so this does not establish CTP/SimNow login, provider/account readiness, production routing, orders, settlement, or write admission. `NO_WRITE / LIVE_NO_GO` remains.

## Historical first-round PyYAML repack

The first frozen-parent run used a locally repacked PyYAML wheel with SHA-256 prefix `c58d7fa7…`; it was not independently verified against the upstream PyPI artifact. Its offline fake/replay smoke passed, but that origin limitation is now historical and is superseded by the official-PyYAML rerun above. The first-round value-free evidence is at `D:\bt_api_execution_candidate_20260925_clean\offline_clean_bundle\frozen_parent_af538469\clean_bundle_smoke_evidence.json`.

## Earlier 60-wheel bundle

The preceding no-system 60-wheel bundle's `12 passed, 2 failed` result is a historical, superseded snapshot; its two managed fake L2 cases failed against the older parent runtime's generic dispatch-freeze resolver. Earlier overlay-backed or inherited-system 14/14 runs are not clean-origin evidence.