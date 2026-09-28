from __future__ import annotations
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

FREEZE = Path(r'D:\temp\ac41-63-controlled-writer-slice-20260927')
MAIN_SOURCE = Path(r'D:\temp\iteration41-writer-inventory-independent-qa-20260927\repo')
R2A_SOURCE = Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2a')
SCRATCH = Path(r'D:\temp\ac41-63-controlled-writer-slice-independent-qa-20260927-r2')
QA = Path(__file__).resolve().parent
ARCHIVE_NAME = 'ac41-63-controlled-writer-slice-20260927.zip'
EXPECTED_ARCHIVE_SHA = '8250D63B8110E450BB20385BD2DD2C006D3C070FBD4121243EF2B8406764FDEF'
EXPECTED_ARCHIVE_MANIFEST_SHA = '769AEFC6C89AF472053881429CBACE8FA0A4DCCD50F739F925DCA8EAEDE2B0FD'
EXPECTED_SOURCE_MANIFEST_SHA = '423CB56E86375019307D252AD774706A259161D7D4EF7B605410EDB0FC889FC6'
EXPECTED_CANDIDATE_MANIFEST_SHA = '5AD9CCE0851FBEBD9AC07D520919B7A02F793AB99A133CF96E91F58CEDE405FB'
EXPECTED_R2A_PATCH_SHA = '7708DF2F0923B74E5F95315390580EB417E9CA05CFA4C6FE41422BC410908E99'
EXPECTED_R2A_STORE_SHA = '18A02F00EC3B2031932284C9E855395C1C70C3E448DBAFCD054E4F079048C4D0'
SELECTED_IDS = [
    'i41-writer-6b64c967597ca9a30e13', 'i41-writer-ed12303a6c97d433f979',
    'i41-writer-e25ef08c3d066b243298', 'i41-writer-8f9ca48eab400d71e549',
    'i41-writer-8739a8fd4212eca086b0', 'i41-writer-f8f51de9f2f4a3fdf72c',
    'i41-writer-b71354cccd4aa34361ee', 'i41-writer-fbe05d71d70ed65a9838',
    'i41-writer-174e9667065d97aae5dd', 'i41-writer-7d767677b3f095e8da32',
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_and_extract_frozen_archive():
    source_zip = FREEZE / ARCHIVE_NAME
    assert sha(source_zip) == EXPECTED_ARCHIVE_SHA, 'frozen ZIP SHA mismatch'
    external_manifest = FREEZE / 'archive-manifest.json'
    assert sha(external_manifest) == EXPECTED_ARCHIVE_MANIFEST_SHA, 'external manifest SHA mismatch'
    frozen_copy = QA / 'frozen-input-ac41-63-controlled-writer-slice.zip'
    if not frozen_copy.exists():
        shutil.copyfile(source_zip, frozen_copy)
    assert sha(frozen_copy) == EXPECTED_ARCHIVE_SHA, 'copied ZIP SHA mismatch'
    extracted = SCRATCH / 'frozen-input'
    extracted.mkdir()
    with zipfile.ZipFile(frozen_copy, 'r') as archive:
        assert archive.testzip() is None, 'ZIP CRC failure'
        names = set(archive.namelist())
        assert 'archive-manifest.json' in names and 'SHA256SUMS.txt' in names
        for name in names:
            member = PurePosixPath(name)
            assert not member.is_absolute() and '..' not in member.parts, 'unsafe ZIP member'
        embedded_manifest_bytes = archive.read('archive-manifest.json')
        assert hashlib.sha256(embedded_manifest_bytes).hexdigest().upper() == EXPECTED_ARCHIVE_MANIFEST_SHA
        manifest = json.loads(embedded_manifest_bytes.decode('utf-8'))
        payloads = manifest['members']
        assert len(payloads) == 25 and len(names) == 27
        assert names == {item['path'] for item in payloads} | {'archive-manifest.json', 'SHA256SUMS.txt'}
        payload_checks = []
        for item in payloads:
            data = archive.read(item['path'])
            actual = hashlib.sha256(data).hexdigest().upper()
            passed = len(data) == item['size_bytes'] and actual == item['sha256'].upper()
            payload_checks.append({'path': item['path'], 'size_bytes': len(data), 'expected_sha256': item['sha256'].upper(), 'actual_sha256': actual, 'passed': passed})
            if not passed:
                raise AssertionError('frozen payload mismatch: ' + item['path'])
        sums = {}
        for line in archive.read('SHA256SUMS.txt').decode('utf-8').splitlines():
            digest, name = line.split(None, 1)
            sums[name.strip()] = digest.upper()
        assert len(sums) == 26 and set(sums) == names - {'SHA256SUMS.txt'}
        for name, expected in sums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest().upper() == expected, 'SHA256SUMS mismatch: ' + name
        archive.extractall(extracted)
    assert (extracted / 'archive-manifest.json').read_bytes() == external_manifest.read_bytes()
    (QA / 'frozen-payload-verification.json').write_text(
        json.dumps({'archive_sha256': EXPECTED_ARCHIVE_SHA, 'archive_manifest_sha256': EXPECTED_ARCHIVE_MANIFEST_SHA, 'zip_members': 27, 'payload_members': 25, 'sha256sum_entries': 26, 'zip_testzip': None, 'payload_checks': payload_checks}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return extracted, frozen_copy


def verify_source_tree(root: Path, manifest_path: Path, label: str):
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    checks = []
    for entry in manifest['files']:
        rel = entry['path']
        pure = PurePosixPath(rel)
        if pure.is_absolute() or '..' in pure.parts:
            raise AssertionError('unsafe source manifest path: ' + rel)
        path = root.joinpath(*pure.parts)
        if not path.is_file():
            raise AssertionError(label + ' source missing: ' + rel)
        actual = sha(path)
        expected = entry['sha256'].upper()
        passed = actual == expected
        checks.append({'path': rel, 'expected_sha256': expected, 'actual_sha256': actual, 'passed': passed})
        if not passed:
            raise AssertionError(label + ' source hash mismatch: ' + rel)
    return {'label': label, 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest().upper(), 'files_checked': len(checks), 'result': 'PASS', 'files': checks}, manifest


def copy_python_packages(source_root: Path, manifest: dict, target: Path, label: str):
    target.mkdir(parents=True)
    copied = []
    for entry in manifest['files']:
        rel = entry['path']
        if not rel.endswith('.py') or not rel.startswith(('backtrader/', 'backtrader_runtime/')):
            continue
        pure = PurePosixPath(rel)
        src = source_root.joinpath(*pure.parts)
        dst = target.joinpath(*pure.parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        actual = sha(dst)
        expected = entry['sha256'].upper()
        if actual != expected:
            raise AssertionError(label + ' copied source mismatch: ' + rel)
        copied.append({'path': rel, 'sha256': actual, 'size_bytes': dst.stat().st_size})
    if not copied:
        raise AssertionError(label + ' copied no package sources')
    return copied


def make_source_snapshot_zip(main_copy: Path, r2a_copy: Path, destination: Path):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for label, root in (('main', main_copy), ('r2a', r2a_copy)):
            for path in sorted(root.rglob('*.py')):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(label + '/' + rel, date_time=(2026, 9, 27, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                info.external_attr = 0
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(destination, 'r') as archive:
        assert archive.testzip() is None
        return len(archive.namelist())


def create_network_import_guard():
    guard_dir = SCRATCH / 'guard'
    guard_dir.mkdir()
    guard_source = r'''import importlib.abc
import json
import os
import sys

log_path = os.environ['QA_GUARD_LOG']
def record(item):
    with open(log_path, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(item, sort_keys=True) + '\\n')

class DenyProviderFinder(importlib.abc.MetaPathFinder):
    blocked = {'bt_api_py', 'bt_api_ctp', 'ctp'}
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0].lower() in self.blocked:
            record({'kind': 'blocked-provider-import', 'module': fullname.split('.', 1)[0]})
            raise ImportError('independent QA blocked provider/native module import')
        return None

sys.meta_path.insert(0, DenyProviderFinder())
def audit(event, args):
    if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'subprocess.Popen'}:
        record({'kind': 'blocked-side-effect', 'event': event})
        raise PermissionError('independent QA blocked network/process side effect')
sys.addaudithook(audit)
'''
    path = guard_dir / 'sitecustomize.py'
    path.write_text(guard_source, encoding='utf-8')
    return guard_dir


def clean_environment(guard_dir: Path, log_path: Path, **extra):
    env = {}
    for key in ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC'):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONUTF8': '1', 'BACKTRADER_LIGHT_IMPORT': '1', 'PYTHONPATH': str(guard_dir), 'QA_GUARD_LOG': str(log_path)})
    env.update({k: str(v) for k, v in extra.items()})
    return env


def run_command(name: str, args: list, cwd: Path, env: dict):
    result = subprocess.run(args, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    (QA / (name + '.stdout.log')).write_bytes(result.stdout)
    (QA / (name + '.stderr.log')).write_bytes(result.stderr)
    (QA / (name + '.exit-code.txt')).write_text(str(result.returncode), encoding='ascii')
    return result


def main():
    allowed_initial = {
        Path(__file__).name, 'frozen-input-ac41-63-controlled-writer-slice.zip',
        'frozen-payload-verification.json', 'input-check.guard.jsonl',
        'input-check.json', 'input-verify.guard.jsonl',
        'input-verify.exit-code.txt', 'input-verify.stderr.log',
        'input-verify.stdout.log', 'python-source-snapshots.zip',
        'source-copy-summary.json', 'source-hash-verification.json',
    }
    if QA.exists() and any(path.name not in allowed_initial for path in QA.iterdir()):
        raise SystemExit('reviewer output directory must start empty')
    if SCRATCH.exists() and any(SCRATCH.iterdir()):
        raise SystemExit('scratch directory must start empty')
    SCRATCH.mkdir(parents=True, exist_ok=True)
    extracted, frozen_copy = validate_and_extract_frozen_archive()

    # Recheck disposition count and the exact 10 selected IDs from an extracted copy.
    guard_dir = create_network_import_guard()
    input_guard = QA / 'input-verify.guard.jsonl'
    input_guard.write_text('', encoding='utf-8')
    env = clean_environment(guard_dir, input_guard)
    input_run = run_command('input-verify', [sys.executable, str(extracted / 'verify_inputs.py')], extracted, env)
    if input_run.returncode != 0:
        raise SystemExit('verify_inputs failed')
    input_check = json.loads((extracted / 'input-check.json').read_text(encoding='utf-8'))
    assert input_check['inventory_counts'] == {'dynamic_execution_candidates': 62, 'files_scanned': 349, 'parse_errors': 0, 'writer_candidates': 327}
    assert input_check['disposition_entries'] == 389 and input_check['selected_count'] == 10
    assert input_check['selected_ids_all_present'] is True and input_check['overall_status'] == 'NOT_CLOSED_STATIC_REVIEW_REQUIRED'
    observed_ids = [item['candidate_id'] for item in input_check['selected_items']]
    assert observed_ids == SELECTED_IDS, 'selected candidate IDs/order mismatch'
    assert input_check['status_counts'] == {"('REVIEW_REQUIRED', 'NOT_AVAILABLE')": 389}
    (QA / 'input-check.json').write_text(json.dumps(input_check, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (QA / 'input-check.guard.jsonl').write_bytes(input_guard.read_bytes())

    main_manifest_path = extracted / 'input' / 'frozen-source-manifest.json'
    assert sha(main_manifest_path) == EXPECTED_SOURCE_MANIFEST_SHA
    main_source_check, main_manifest = verify_source_tree(MAIN_SOURCE, main_manifest_path, 'frozen-main-source')
    r2a_manifest_path = extracted / 'input' / 'r2a' / 'candidate-manifest.json'
    assert sha(r2a_manifest_path) == EXPECTED_CANDIDATE_MANIFEST_SHA
    r2a_manifest = json.loads(r2a_manifest_path.read_text(encoding='utf-8'))
    r2a_sum = (extracted / 'input' / 'r2a' / 'candidate-manifest.sha256').read_text(encoding='ascii').split()[0].upper()
    assert r2a_sum == EXPECTED_CANDIDATE_MANIFEST_SHA
    r2a_source_check, r2a_source_manifest = verify_source_tree(R2A_SOURCE, r2a_manifest_path, 'r2a-candidate-source')
    patch_sha = sha(extracted / 'input' / 'r2a' / 'r2a-apply.patch')
    r2a_store_sha = sha(R2A_SOURCE / 'backtrader' / 'stores' / 'btapistore.py')
    assert patch_sha == EXPECTED_R2A_PATCH_SHA and r2a_store_sha == EXPECTED_R2A_STORE_SHA
    private_paths = [e['path'] for e in main_manifest['files'] + r2a_manifest['files'] if any(token in e['path'].lower() for token in ('.env', 'runtime-ctp-private', 'private-state'))]
    assert not private_paths, 'private config path found in source manifests'
    (QA / 'source-hash-verification.json').write_text(json.dumps({'main': main_source_check, 'r2a': r2a_source_check, 'r2a_patch_sha256': patch_sha, 'r2a_store_sha256': r2a_store_sha, 'candidate_manifest_sha256': EXPECTED_CANDIDATE_MANIFEST_SHA, 'private_path_candidates': private_paths, 'scope': 'hash-only verification; source package copies below contain Python files only, no config/env files'}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    main_copy = SCRATCH / 'source-main'
    r2a_copy = SCRATCH / 'source-r2a'
    main_copied = copy_python_packages(MAIN_SOURCE, main_manifest, main_copy, 'main')
    r2a_copied = copy_python_packages(R2A_SOURCE, r2a_source_manifest, r2a_copy, 'r2a')
    source_zip = QA / 'python-source-snapshots.zip'
    source_zip_members = make_source_snapshot_zip(main_copy, r2a_copy, source_zip)
    (QA / 'source-copy-summary.json').write_text(json.dumps({'main_python_files_copied': len(main_copied), 'r2a_python_files_copied': len(r2a_copied), 'source_snapshot_zip_members': source_zip_members, 'main_key_source_sha256': {rel: sha(MAIN_SOURCE / rel) for rel in ('backtrader/stores/btapistore.py', 'backtrader/stores/managed_execution.py', 'backtrader_runtime/cli.py', 'backtrader_runtime/runner.py', 'backtrader_runtime/inventory.py', 'backtrader_runtime/registry.py', 'backtrader_runtime/policy.py')}, 'r2a_store_sha256': r2a_store_sha, 'non_python_files_copied': 0}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    # Probe copy is from the verified frozen ZIP. The run environment is allowlisted;
    # socket/process and CTP/native imports are blocked by sitecustomize traps.
    probe_path = extracted / 'run_slice_probe.py'
    assert sha(probe_path) == 'F541163077A68F899206080529DECB33BD3CF320AAB8154DFFF6B0CF62B6B23C'
    for mode, source_root in (('main', main_copy), ('r2a', r2a_copy)):
        guard_path = QA / (mode + '-probe.guard.jsonl')
        guard_path.write_text('', encoding='utf-8')
        env = clean_environment(guard_dir, guard_path, QA_SOURCE_ROOT=source_root, QA_MODE=mode)
        run = run_command(mode + '-probe', [sys.executable, str(probe_path)], extracted, env)
        if run.returncode != 0:
            raise SystemExit(mode + ' probe failed; see raw stderr')
        output = json.loads(run.stdout.decode('utf-8'))
        if output['source_root'] != str(source_root.resolve()):
            raise AssertionError(mode + ' source root mismatch')
        (QA / (mode + '-probe.json')).write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        events = [line for line in guard_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if events:
            raise AssertionError(mode + ' side-effect/import guard observed events: ' + repr(events))
    main_out = read_json(QA / 'main-probe.json')
    r2a_out = read_json(QA / 'r2a-probe.json')
    main_probes = {p['name']: p for p in main_out['probes']}
    r2a_probes = {p['name']: p for p in r2a_out['probes']}
    assert main_out['btapistore_sha256'].upper() == 'DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826'
    assert main_probes['default registered CTP private preflight']['outcome'] == 'REJECTED_BEFORE_CONFIG_OR_PROVIDER'
    assert main_probes['default registered CTP private preflight']['exit_code'] == 2
    assert main_probes['default registered CTP private preflight']['protected_open_attempts'] == 0
    assert main_probes['default registered CTP private preflight']['sdk_modules_loaded'] == []
    assert main_probes['registered runner dynamic import gates']['outcome'] == 'REJECTED_BEFORE_IMPORT'
    assert main_probes['main public and private CTP legacy methods']['outcome'] == 'FAKE_BOUNDARIES_REACHED'
    assert main_probes['main gateway wrapper direct methods']['outcome'] == 'FAKE_BOUNDARY_TRAPPED'
    assert main_probes['lazy CTP SDK resolver']['attempted_module_names'] == ['bt_api_py']
    assert main_probes['CTP constructor gate ordering']['outcome'] == 'STATIC_PRE_GATE_ATTRIBUTE_AND_ENV_READS'
    assert main_probes['synthetic environment provider/exchange rewrite']['outcome'] == 'RECLASSIFIED_TO_NON_CTP'
    assert r2a_out['btapistore_sha256'].upper() == EXPECTED_R2A_STORE_SHA
    assert r2a_probes['r2a explicit CTP constructor order']['outcome'] == 'REJECTED_BEFORE_ENV_OR_OBJECT_READ'
    assert r2a_probes['r2a actor-only internal legacy methods']['outcome'] == 'BLOCKED_AT_METHOD_ENTRY'
    assert r2a_probes['r2a gateway wrapper direct methods']['outcome'] == 'FAKE_BOUNDARY_TRAPPED'

    report = f'''# AC41-63 controlled-writer slice: independent QA

**Disposition: `10/389 PARTIAL / AC41-63 NOT_ACCEPTED`.** This rerun verifies only the frozen 10-candidate slice and early default CLI rejection. It does not close the other 379 inventory dispositions, authorize a CTP route, or establish G4/F14 acceptance.

## Frozen input and isolated replay

- Author input ZIP SHA-256: `{EXPECTED_ARCHIVE_SHA}`; archive manifest SHA-256: `{EXPECTED_ARCHIVE_MANIFEST_SHA}`. The 27 ZIP members passed CRC, 25 payload hashes matched the embedded manifest, and the 26 `SHA256SUMS.txt` entries matched.
- Source manifests: main frozen tree `{EXPECTED_SOURCE_MANIFEST_SHA}` ({main_source_check['files_checked']} files hash-verified); r2a candidate `{EXPECTED_CANDIDATE_MANIFEST_SHA}` ({r2a_source_check['files_checked']} payload hashes hash-verified). r2a patch `{patch_sha}`, r2a Store `{r2a_store_sha}`. The new source copies contain package `.py` files only; no `.env`, private runtime directory, or config file was copied.
- `verify_inputs.py` rerun against the ZIP extraction confirmed **349 files / 327 writer candidates / 62 dynamic candidates / 0 parse errors / 389 dispositions**. The exact 10 requested IDs are present and all 389 remain `REVIEW_REQUIRED / NOT_AVAILABLE`; 379 were not reviewed here.
- Main and r2a probes ran in separate Python processes with a minimal allowlisted environment. A startup guard blocks CTP/native module imports, sockets/network audit events, and child-process creation. Guard logs were empty. Delegates are inert fakes or traps; no account/provider/order, real SDK/native module, private config, or network was used.

## Replayed results

- **Default CLI preflight:** the probe called frozen `backtrader_runtime.cli.main([...], registry=default_runtime_registry(), environ={{}})` in-process; it did not launch a shell `bt-runtime` entry point. The registered 013_3 private `preflight` returned exit 2, reason `ctp_simnow_preflight_supervisor_required`; config open attempts 0, validation/provider-preflight traps untouched, and CTP/native SDK module list empty. Two runner dispatch policy cases rejected before profile attribute access and dynamic import. This is the `preflight` CLI boundary only; the `run` branch is not claimed config-free.
- **Main public Python Store and gateway surfaces:** frozen-AST `submit_order`, `cancel_order`, `_submit_order_legacy`, and `_cancel_order_ref_legacy` reached fake API traps. The three `CtpGatewayClientWrapper` methods reached fake client traps. Thus the default CLI early rejection is not a global fail-closed result for direct Python objects. The main Store constructor has a static ordering gap: generic adapter attribute inspection and CTP config/environment/API-kwargs access precede typed CTP authorization validation.
- **r2a constructor and actor-only methods:** explicit CTP construction rejected before env/caller-object reads; four actor-only internal methods rejected at entry with zero fake API calls. The r2a gateway wrapper still delegated its three methods to a fake client. This preserves the wrapper gap and does not establish an external actor lifecycle.
- **Provider/exchange selector:** only synthetic mappings were used. The exact main AST resolved requested `ctp` plus synthetic `BT_STORE_PROVIDER=okx_gateway` / `BT_GATEWAY_EXCHANGE_TYPE=BINANCE` to gateway/non-CTP. No client was built and no writer called; this is a direct-Python route-label observation, not CTP dispatch evidence.

## Boundary

The public Python Store/gateway delegate paths are callable in the inert fake harness while default registered CLI `preflight` rejects early. r2a closes its explicit constructor and actor-only helper paths, but not its separate wrapper delegate. The 10-of-389 cut remains partial and non-authorizing. Native method fallback/reflection, arbitrary adapters, all 379 other candidates, production composition, real SDK/provider behavior, and account-level writer exclusivity remain untested.

## Reproduction

The recorded reviewer command was `python -B independent_qa_driver.py`. The successful main and r2a probe processes used new Python-only source copies in an isolated scratch root; earlier archive/input-hash preparation files in the reviewer directory were regenerated or verified before the final manifest was written. The driver uses frozen source roots named in its source and checks them against their manifests; raw logs, hash reports, the frozen author ZIP, and a Python-only source snapshot ZIP are preserved here. It is an evidence-generation script, not an in-place rerun command for this now-frozen directory. The tested CLI boundary was the in-process `cli.main` call described above, not the packaged shell entry point.
'''
    (QA / 'QA-REPORT.md').write_text(report, encoding='utf-8')
    (QA / 'independent_qa_driver.py').write_text(Path(__file__).read_text(encoding='utf-8'), encoding='utf-8')
    make_source_snapshot_zip(main_copy, r2a_copy, source_zip)

    # A manifest over every archived reviewer payload except itself and the final ZIP.
    excluded = {'manifest.json', 'manifest.sha256', 'ac41-63-controlled-writer-slice-independent-qa.raw.zip', 'ac41-63-controlled-writer-slice-independent-qa.raw.zip.sha256'}
    payloads = []
    for path in sorted(QA.rglob('*')):
        if not path.is_file() or path.name in excluded:
            continue
        rel = path.relative_to(QA).as_posix()
        payloads.append({'path': rel, 'size_bytes': path.stat().st_size, 'sha256': sha(path)})
    manifest = {
        'schema': 'ac41-63-controlled-writer-slice-reviewer-qa-v1',
        'status': '10/389 PARTIAL / AC41-63 NOT_ACCEPTED',
        'python': platform.python_version(),
        'platform': sys.platform,
        'author_zip_sha256': EXPECTED_ARCHIVE_SHA,
        'author_manifest_sha256': EXPECTED_ARCHIVE_MANIFEST_SHA,
        'main_source_manifest_sha256': EXPECTED_SOURCE_MANIFEST_SHA,
        'r2a_candidate_manifest_sha256': EXPECTED_CANDIDATE_MANIFEST_SHA,
        'r2a_patch_sha256': patch_sha,
        'r2a_store_sha256': r2a_store_sha,
        'inventory': input_check['inventory_counts'],
        'reviewed_ids': SELECTED_IDS,
        'reviewed_count': 10,
        'total_candidate_count': 389,
        'unreviewed_count': 379,
        'probe_exit_codes': {'input-verify': input_run.returncode, 'main-probe': int((QA / 'main-probe.exit-code.txt').read_text()), 'r2a-probe': int((QA / 'r2a-probe.exit-code.txt').read_text())},
        'safety': {'no_private_config_copied_or_read': True, 'no_network_events': True, 'no_provider_or_native_imports': True, 'no_subprocess_attempts_from_probe': True, 'delegates_fake_or_trapped': True, 'real_order_or_cancel': False},
        'payloads': payloads,
    }
    (QA / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    manifest_sha = sha(QA / 'manifest.json')
    (QA / 'manifest.sha256').write_text(manifest_sha + '  manifest.json\n', encoding='ascii')
    zip_path = QA / 'ac41-63-controlled-writer-slice-independent-qa.raw.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(QA.rglob('*')):
            if not path.is_file() or path == zip_path or path.name == zip_path.name + '.sha256':
                continue
            rel = path.relative_to(QA).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026, 9, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    zip_sha = sha(zip_path)
    (QA / (zip_path.name + '.sha256')).write_text(zip_sha + '  ' + zip_path.name + '\n', encoding='ascii')
    with zipfile.ZipFile(zip_path, 'r') as archive:
        assert archive.testzip() is None
        assert 'manifest.json' in archive.namelist() and 'manifest.sha256' in archive.namelist()
    print(json.dumps({'status': manifest['status'], 'archive_sha256': EXPECTED_ARCHIVE_SHA, 'archive_manifest_sha256': EXPECTED_ARCHIVE_MANIFEST_SHA, 'main_verified_files': main_source_check['files_checked'], 'r2a_verified_files': r2a_source_check['files_checked'], 'main_python_copy_count': len(main_copied), 'r2a_python_copy_count': len(r2a_copied), 'input_counts': input_check['inventory_counts'], 'selected_count': input_check['selected_count'], 'main_exit': int((QA / 'main-probe.exit-code.txt').read_text()), 'r2a_exit': int((QA / 'r2a-probe.exit-code.txt').read_text()), 'qa_manifest_sha256': manifest_sha, 'qa_zip_sha256': zip_sha, 'qa_zip_bytes': zip_path.stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
