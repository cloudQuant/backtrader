import ast
from pathlib import Path
files = {
'g5_authority': (Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py'), ['reserve_cancel_action_identity','stage_cancel_command']),
'g5_worker': (Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py'), ['stage_prepared_dispatch']),
'g5_store': (Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\store.py'), []),
'g5_bridge': (Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\backtrader_bridge\ctp_order_action_bridge.py'), ['cancel_order']),
'g5_builder': (Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\main_repo_patch\backtrader\stores\ctp_i9_parent_request_builder.py'), []),
'v21_store': (Path(r'D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src\bt_api_execution\store.py'), ['_allocate_ctp_native_action_ref','stage_ctp_dispatch_command','_migrate_legacy_ctp_action_ref_accounts']),
'v21_worker': (Path(r'D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src\bt_api_execution\ctp_single_worker_candidate.py'), ['stage_prepared_dispatch']),
}
for label,(path,names) in files.items():
    source=path.read_text(encoding='utf-8'); lines=source.splitlines(); tree=ast.parse(source)
    print(f'===== {label}: {path} =====')
    if label=='g5_store':
        for i,line in enumerate(lines,1):
            if '_SCHEMA_VERSION' in line or 'CREATE TABLE IF NOT EXISTS ctp_action' in line or 'ctp_action_identity_reservations' in line or 'ctp_action_ref_watermarks' in line:
                print(f'{i}: {line}')
    if label=='v21_store':
        for i,line in enumerate(lines,1):
            if '_SCHEMA_VERSION' in line or 'CREATE TABLE IF NOT EXISTS ctp_native_action_ref' in line or 'ctp_native_action_ref_counters' in line or 'ctp_native_action_ref_allocations' in line:
                if i < 6000 or i > 9000: print(f'{i}: {line}')
    if label=='g5_builder':
        for i,line in enumerate(lines,1):
            if 'reserve_cancel_action_identity' in line or 'action_identity=' in line or 'stage_prepared_dispatch' in line:
                print(f'{i}: {line}')
    if label=='g5_bridge':
        for i,line in enumerate(lines,1):
            if 'reserve_cancel_action_identity' in line or 'stage_cancel_command' in line or 'native_action_ref' in line:
                print(f'{i}: {line}')
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            print(f'--- def {node.name} lines {node.lineno}-{node.end_lineno} ---')
            for i in range(node.lineno,node.end_lineno+1): print(f'{i}: {lines[i-1]}')
