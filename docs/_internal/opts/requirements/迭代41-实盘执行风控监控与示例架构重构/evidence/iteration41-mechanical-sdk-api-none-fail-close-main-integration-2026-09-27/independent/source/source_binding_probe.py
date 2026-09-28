import hashlib, json, pathlib, sys
names = ('ctp_options_simnow_operator.py','ctp_options_simnow_mechanical_operator.py','ctp_options_simnow_approval_issuer.py','ctp_options_simnow_authorization.py','ctp_options_simnow_common.py','ctp_options_simnow_mechanical_cycle.py','ctp_options_simnow_live_drive.py','ctp_options_simnow_live_runner.py')
def compute(root):
    hashes = {name: hashlib.sha256((pathlib.Path(root)/name).read_bytes()).hexdigest() for name in names}
    serialized = json.dumps(hashes, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashes, hashlib.sha256(serialized).hexdigest()
base, base_digest = compute(sys.argv[1]); candidate, candidate_digest = compute(sys.argv[2])
print(json.dumps({'base_source_hashes_sha256':base_digest,'candidate_source_hashes_sha256':candidate_digest,'changed_source_names':[n for n in names if base[n] != candidate[n]],'digest_changed':base_digest != candidate_digest}, indent=2, sort_keys=True))
