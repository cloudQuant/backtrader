import hashlib,json
from pathlib import Path
qa=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927')
cand=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
static=json.loads((qa/'evidence'/'artifact-static-audit.json').read_text(encoding='utf-8'))
installed=json.loads((qa/'evidence'/'install-record-origin-audit.json').read_text(encoding='utf-8'))
base=json.loads((qa/'evidence'/'base-source-comparison.json').read_text(encoding='utf-8'))
wheel_source=json.loads((qa/'evidence'/'clean-g4-client-wheel-readback.json').read_text(encoding='utf-8'))
settle=json.loads((qa/'evidence'/'settlement-wheel-helper-readback.json').read_text(encoding='utf-8'))
checks={
 'candidate_files_manifest_sha256':sha(cand/'candidate-files-manifest.json'),
 'candidate_archive_sha256':sha(cand/'unified-offline-wheelhouse-settlement-evidence-r1.zip'),
 'candidate_receipt_sha256':sha(cand/'candidate-receipt.json'),
 'candidate_requirements_lock_sha256':sha(cand/'requirements-hashes.txt'),
 'candidate_wheelhouse_manifest_sha256':sha(cand/'wheelhouse-manifest.json'),
 'candidate_archive_index_sha256':sha(cand/'archive-index.json'),
 'qa_artifact_static_audit_sha256':sha(qa/'evidence'/'artifact-static-audit.json'),
 'qa_install_record_origin_audit_sha256':sha(qa/'evidence'/'install-record-origin-audit.json'),
 'qa_base_source_comparison_sha256':sha(qa/'evidence'/'base-source-comparison.json'),
 'qa_clean_g4_client_readback_sha256':sha(qa/'evidence'/'clean-g4-client-wheel-readback.json'),
 'qa_settlement_wheel_helper_readback_sha256':sha(qa/'evidence'/'settlement-wheel-helper-readback.json')
}
obj={
 'schema':'iteration41.unified_offline_wheelhouse_settlement.independent_qa_receipt.r1.v1',
 'classification':'FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED',
 'candidate':{'root':str(cand),'payload_files':static['manifest_payload_files_verified'],'archive_entries':static['candidate_archive_entries'],'archive_crc_and_payload_hashes':'passed','requirements_lock_lines':static['requirements_lock_lines'],'wheelhouse_count':static['wheel_count']},
 'installation':{'interpreter':'CPython 3.11.5 Windows x64','venv':installed['venv_path'],'system_site_packages':False,'pip':'23.2.1','index_access':False,'require_hashes':True,'selected_wheel_count':installed['pip_install_entries'],'local_file_origins_verified':True,'direct_root_installs':installed['pep610_root_artifacts'],'pip_check':installed['pip_check'],'installed_record_rows_checked':installed['record_rows_checked'],'record_errors':installed['errors'],'native_modules_loaded':installed['loaded_native_modules'],'ctp_modules_loaded':installed['loaded_ctp_modules']},
 'artifact_checks':{'ctp_wheel_unique_version':static['ctp_final'],'clean_base_source':base,'binance_optional_extra':static['missing_optional_extra'],'clean_g4_client_source':wheel_source,'settlement_helper':settle},
 'settlement_limits':{'response_row_field':'ConfirmDate','response_row_has_TradingDay':False,'helper_compares_ConfirmDate_with_separate_query_source_TradingDay':True,'helper_consumed_by_main_readiness':False,'therefore_no_live_settlement_proof_or_authority':True},
 'scope':{'sdk_imported':False,'native_loaded_or_called':False,'private_config_or_credentials_read':False,'provider_or_network_called':False,'default_pin_or_main_route_changed':False},
 'candidate_source_hashes':checks,
 'independent_commands':{'hash_locked_offline_install':'--no-index --find-links <frozen wheelhouse> --require-hashes -r requirements-hashes.txt','pip_check':'No broken requirements found.','record_audit':'13,147 rows, zero errors','ctpsettlement_focused_pytest_rerun':False},
 'qa_harness_notes':'Three initial QA-only assertion/schema mistakes were corrected after direct source/manifest inspection; initial stdout/exit logs and successful reruns are preserved. The initial static-audit JSON was overwritten before it was copied aside; its diagnostic log remains. No candidate source or wheelhouse bytes were modified.',
 'status':'FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED'
}
(qa/'QA-RECEIPT.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'receipt_sha256':sha(qa/'QA-RECEIPT.json'),'candidate_hashes':checks,'status':obj['status']},indent=2))

