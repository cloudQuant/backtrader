# Independent QA receipt: 013_3 local replay r2

**Verdict: `SAFE_TO_APPLY_LOCAL_REPLAY_ONLY`.** This verdict is limited to the frozen two-file local replay patch and its tests. It is not production acceptance, CTP/SimNow acceptance, G1 acceptance, SDK acceptance, or authority to enable a default route. No main-worktree production file was edited by this QA.

## Frozen author input

- Package: `D:\temp\iteration41-0133-local-replay-r2b-candidate-20260927\author-package-r2`
- Manifest SHA-256: `14F75238DFAB2959DF32642017E52F9AB0E1D54C6B6E02BCC87FF47906A9642D`
- Patch `evidence\local-replay.patch` SHA-256: `B8DD2AE3B0BD108B4445E9D7B261515F0062DB678D6792364F4E22EF32034473`
- Author ZIP `D:\temp\iteration41-0133-local-replay-r2b-candidate-20260927\evidence\iteration41-0133-local-replay-r2-author-candidate.zip` SHA-256: `EF6C629784077E016B1B6E8FFA34F3BD23ADB35C6184D68560A672B1F396A186`
- Independently verified all 87/87 manifest payloads for path, size, and SHA-256. ZIP has 88 entries (87 payloads plus manifest), `ZipFile.testzip()` returned `None`, and every archived payload matched the frozen package bytes. No `.env` or `runtime-ctp-private` path is present.

## Exact-main patch reproduction

The patch was applied in a disposable QA directory from the current main-worktree target bytes. Before-apply SHA-256 values matched the author baseline: `run.py` `16D6A184F1A57C0C2843511DD0BD7ADA4825D945402665BE1AAF8B624FC9576C`; test `146833DF60C0C847E5AC64C1F8239673E525F5C08DDA86453CF81B3B11327CD5`.

`git -C "D:\temp\iteration41-0133-local-replay-r2-independent-qa-20260927\patch-exact-main-rerun" -c core.autocrlf=false apply --check "D:\temp\iteration41-0133-local-replay-r2b-candidate-20260927\author-package-r2\evidence\local-replay.patch"` returned 0; apply returned 0; `git diff --check` returned 0. Resulting files are byte-identical to the frozen candidate: `run.py` `1C3D37A7485C05EC4EBB82BA1A66218B6B739063E04819D7B327BA4D8847B58E`; test `00F9DB83E22735539920A7F033AB0A888906ECF61109C156513BCFE1D9C64678`.

The independently assembled source snapshot contains 607 files and is bound by `evidence\qa-source-manifest.json` SHA-256 `45B4637E18F7A978E77E7F3BB5AE8E543AFEC93A38A7D338A52500BD5A617EF6`. The r2b Store overlay hashes are `btapistore.py` `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518` and `ctp_account_actor_port.py` `2E4B04D00C45BA9C6524C5AD0364273E6ECC1A1F653F595D21C3891BE2644EE3`. The copied `examples/013_3_sa_midfreq_simnow/config.yaml` equals the tracked main file byte-for-byte (SHA-256 `AAF85B1E682D2E872022D2B15ABC9F56CF80023CD2DC59E03399FFCD079986F1`); no `.env` or private runtime directory was copied.

## Guarded independent tests

Interpreter: CPython 3.11.5, `D:\source_code\backtrader\.venv\Scripts\python.exe`. Pytest was run with plugin autoload disabled, the source-copy directory and independent guard on `PYTHONPATH`, `-B`, and `-p no:asyncio`:

```text
python -B -m pytest -p no:asyncio -c <QA source\pytest.ini> -q --tb=short --junitxml <QA logs\focused-final.junit.xml> --basetemp D:\temp\iteration41-0133-r2-pytest-temp-final-20260927
  tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py::test_runtime_identity_probe_does_not_import_sdk_parent_package
  tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py::test_0133_local_replay_composition_has_no_provider_or_order_entry
  tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py::test_real_replay_has_no_network_or_provider_writes[013_3]
```

Result: **3 passed**, exit 0. One existing `DeprecationWarning` was emitted for `backtrader.feeds.quandl`; no test failed. The fake poisoned `bt_api_py` parent initializer test verified module specs while its marker stayed absent and the parent remained out of `sys.modules`.

An independent `sitecustomize` guard removed 14 `D:\bt_api_py` source entries from `sys.path` before test code, then installed a meta-path blocker for all `bt_api_py` imports. Both the focused-test process and a separate guarded replay probe recorded zero provider import attempts, zero preloaded/loaded `bt_api_py` modules, and zero detected CTP native modules. The replay tests also patched network calls, CTP Store/Broker constructors and order methods, and `BackBroker.next` to fail and count any reach. All counters were zero.

## Harness-only failed launches\n\nTwo early guarded pytest command attempts stopped before test collection: the first placed `--basetemp` under the checkout parent, which pytest rejects; the second used PowerShell option binding that caused the JUnit destination to be parsed as a test path. Their stdout and exit files remain in `logs\focused.stdout.log`, `logs\focused.exit`, `logs\focused-rerun.stdout.log`, and `logs\focused-rerun.exit`. They ran no tests and are excluded from the verdict; the final invocation above is the successful run.\n\n## Independent replay output

A separate guarded execution of the frozen synthetic `no_signal` fixture returned `LOCAL_REPLAY_PASS` and these asserted values: 7,500 qualified quotes; 106 qualified completed bars; 64 closed bars; 0 signal/order/trade events; empty orders; 0 position lots; 0 SDK writes; 0 network requests; and 0 provider-construction, provider-write, or inherited-matcher calls. Runtime chain was `LocalReplayStore` → `BtApiFeed(provider=local_replay)` and `LocalReplayBroker`. Scope was `LOCAL_REPLAY_ONLY`, research remained `RESEARCH_NOT_ESTABLISHED`, and the report retained `INDEPENDENT_SIMNOW_ADMISSION_REQUIRED`.

The 19 generated replay-output files are individually hashed in `evidence\replay-output-manifest.json` (manifest SHA-256 `11B31856793B8277213DC834714BE2F94115B6D2E117BD1429CED0F76D6C6F5D`). This QA rechecked fixture counts and zero-write/runtime-chain assertions; it did not rerun the historical 18-file baseline/candidate artifact comparison. That comparison remains historical r1 evidence only.

## Historical contamination remains separate

The r1 QA remains `NEEDS_REVISION` and unchanged: receipt SHA-256 `3FC464042BE91966730D7C2AB7527722AC4B5D2E543671D558EBB8080F612038`, manifest SHA-256 `4C9DDEB92E15CB7874115B9A77E8B83EDA589C0D8648579CC2024C3FEC0510C9`. Copies are preserved under `evidence\historical\r1\`; the original author ZIP is SHA-256 `B544A4B670B1525AE39580CB0A3DCDC0CBDE0A2AE859DB4BBD7A3379B992C9CC`. Its static SDK initializer note SHA-256 is `49A74953F046AC4090153EB364DA3BA1177934AB4E4A98D4124370CAE8E1CBBE`; it observed no direct client/network construction in the initializer text, but that static inspection does not establish transitive import safety. The new r2 startup guard and poisoned-parent test provide the relevant import-safety evidence. The r2 pre-fix unguarded 2/2 run is also preserved but unqualified: stdout SHA-256 `D36FE6751A4D31DCFB3DC8C6F2EA73315387114686928F9B2C290DC5DD0C1EF2`, JUnit SHA-256 `AAB900D38D45F13DBF19CAB6A5220E7A61F1DEF1F0C64241487BBF91E4ABFD9D`. Neither result is counted toward this r2 verdict.

## Boundaries

The evidence exercises a deterministic, synthetic local replay only. It does not use the SDK, credentials, provider, network, native CTP module, account, or write route. It does not establish the safety or availability of a live session, real SimNow, production runner, actor service, broker gateway, or Windows G1 supervisor. Applying this patch cannot open those paths; keep the registry, preflight, and default route unchanged.

## Reproduction artifacts

Independent scripts, raw stdout/JUnit, exit files, startup guard reports, exact-main apply logs, source manifest, and replay-output manifest are under `D:\temp\iteration41-0133-local-replay-r2-independent-qa-20260927`. The author package verification log is `logs\author-package-verification.log`; exact patch reproduction is `logs\patch-exact-main-repro.log`; focused run is `logs\focused-final.stdout.log` and `logs\focused-final.junit.xml`; replay metrics are `logs\invariants.stdout.log`.



