# AC41-63 controlled-writer slice: independent QA

**Disposition: `10/389 PARTIAL / AC41-63 NOT_ACCEPTED`.** This rerun verifies only the frozen 10-candidate slice and early default CLI rejection. It does not close the other 379 inventory dispositions, authorize a CTP route, or establish G4/F14 acceptance.

## Frozen input and isolated replay

- Author input ZIP SHA-256: `8250D63B8110E450BB20385BD2DD2C006D3C070FBD4121243EF2B8406764FDEF`; archive manifest SHA-256: `769AEFC6C89AF472053881429CBACE8FA0A4DCCD50F739F925DCA8EAEDE2B0FD`. The 27 ZIP members passed CRC, 25 payload hashes matched the embedded manifest, and the 26 `SHA256SUMS.txt` entries matched.
- Source manifests: main frozen tree `423CB56E86375019307D252AD774706A259161D7D4EF7B605410EDB0FC889FC6` (362 files hash-verified); r2a candidate `5AD9CCE0851FBEBD9AC07D520919B7A02F793AB99A133CF96E91F58CEDE405FB` (679 payload hashes hash-verified). r2a patch `7708DF2F0923B74E5F95315390580EB417E9CA05CFA4C6FE41422BC410908E99`, r2a Store `18A02F00EC3B2031932284C9E855395C1C70C3E448DBAFCD054E4F079048C4D0`. The new source copies contain package `.py` files only; no `.env`, private runtime directory, or config file was copied.
- `verify_inputs.py` rerun against the ZIP extraction confirmed **349 files / 327 writer candidates / 62 dynamic candidates / 0 parse errors / 389 dispositions**. The exact 10 requested IDs are present and all 389 remain `REVIEW_REQUIRED / NOT_AVAILABLE`; 379 were not reviewed here.
- Main and r2a probes ran in separate Python processes with a minimal allowlisted environment. A startup guard blocks CTP/native module imports, sockets/network audit events, and child-process creation. Guard logs were empty. Delegates are inert fakes or traps; no account/provider/order, real SDK/native module, private config, or network was used.

## Replayed results

- **Default CLI preflight:** the probe called frozen `backtrader_runtime.cli.main([...], registry=default_runtime_registry(), environ={})` in-process; it did not launch a shell `bt-runtime` entry point. The registered 013_3 private `preflight` returned exit 2, reason `ctp_simnow_preflight_supervisor_required`; config open attempts 0, validation/provider-preflight traps untouched, and CTP/native SDK module list empty. Two runner dispatch policy cases rejected before profile attribute access and dynamic import. This is the `preflight` CLI boundary only; the `run` branch is not claimed config-free.
- **Main public Python Store and gateway surfaces:** frozen-AST `submit_order`, `cancel_order`, `_submit_order_legacy`, and `_cancel_order_ref_legacy` reached fake API traps. The three `CtpGatewayClientWrapper` methods reached fake client traps. Thus the default CLI early rejection is not a global fail-closed result for direct Python objects. The main Store constructor has a static ordering gap: generic adapter attribute inspection and CTP config/environment/API-kwargs access precede typed CTP authorization validation.
- **r2a constructor and actor-only methods:** explicit CTP construction rejected before env/caller-object reads; four actor-only internal methods rejected at entry with zero fake API calls. The r2a gateway wrapper still delegated its three methods to a fake client. This preserves the wrapper gap and does not establish an external actor lifecycle.
- **Provider/exchange selector:** only synthetic mappings were used. The exact main AST resolved requested `ctp` plus synthetic `BT_STORE_PROVIDER=okx_gateway` / `BT_GATEWAY_EXCHANGE_TYPE=BINANCE` to gateway/non-CTP. No client was built and no writer called; this is a direct-Python route-label observation, not CTP dispatch evidence.

## Boundary

The public Python Store/gateway delegate paths are callable in the inert fake harness while default registered CLI `preflight` rejects early. r2a closes its explicit constructor and actor-only helper paths, but not its separate wrapper delegate. The 10-of-389 cut remains partial and non-authorizing. Native method fallback/reflection, arbitrary adapters, all 379 other candidates, production composition, real SDK/provider behavior, and account-level writer exclusivity remain untested.

## Reproduction

The recorded reviewer command was `python -B independent_qa_driver.py`. The successful main and r2a probe processes used new Python-only source copies in an isolated scratch root; earlier archive/input-hash preparation files in the reviewer directory were regenerated or verified before the final manifest was written. The driver uses frozen source roots named in its source and checks them against their manifests; raw logs, hash reports, the frozen author ZIP, and a Python-only source snapshot ZIP are preserved here. It is an evidence-generation script, not an in-place rerun command for this now-frozen directory. The tested CLI boundary was the in-process `cli.main` call described above, not the packaged shell entry point.
