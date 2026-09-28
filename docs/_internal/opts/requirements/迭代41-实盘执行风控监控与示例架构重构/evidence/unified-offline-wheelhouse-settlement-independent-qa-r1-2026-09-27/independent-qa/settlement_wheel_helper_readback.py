import hashlib,json,zipfile
from pathlib import Path
cand=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
wheel=cand/'wheelhouse'/'bt_api_ctp-2.0.4+g4r2.settlement.probe.20260927-cp311-cp311-win_amd64.whl'
diff=json.loads((cand/'ctp-source-diff.json').read_text(encoding='utf-8'))
expected=next(x['sha256'].lower() for x in diff['source_files'] if x['path']=='src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py')
with zipfile.ZipFile(wheel) as z:
 raw=z.read('bt_api_ctp/containers/ctp/ctp_native_query_certificate.py')
 source=raw.decode('utf-8')
 sha=hashlib.sha256(raw).hexdigest()
 has_confirm='ConfirmDate' in source and 'scope.trading_day' in source
 has_native_row_check='row_trading_day' in source and 'TradingDay' in source
 result={'schema':'iteration41.unified_offline_wheelhouse_settlement.wheel_helper_readback.r1.v1','wheel':wheel.name,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'wheel_helper_path':'bt_api_ctp/containers/ctp/ctp_native_query_certificate.py','wheel_helper_sha256':sha,'matches_source_overlay_manifest':sha==expected,'expected_source_overlay_sha256':expected,'checks_confirm_date_against_scope_trading_day':has_confirm,'conditionally_checks_row_trading_day_if_present':has_native_row_check,'native_imported':False}
 out=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\evidence\settlement-wheel-helper-readback.json')
 out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(result,indent=2))
 if not result['matches_source_overlay_manifest'] or not has_confirm or not has_native_row_check: raise SystemExit(1)
