import os, runpy, shutil, sys, tempfile
from pathlib import Path
ns = runpy.run_path(str(Path('tests/unit/runtime/test_ctp_sdk_artifact_binding.py')))
binding = ns['binding']; build = ns['_build_fake_distribution']; standard = ns['_use_standard_import_chain']
class MiniPatch:
    @staticmethod
    def setattr(obj,name,value): setattr(obj,name,value)
original_path,original_meta,original_hooks,original_cache=sys.path,sys.meta_path,sys.path_hooks,sys.path_importer_cache
original_policy=binding._CODE_OWNED_ARTIFACT_POLICY
root=Path(os.environ['USERPROFILE'])/'Temp'/('iter41-r2-pyd-custody-'+next(tempfile._get_candidate_names()));root.mkdir();importer=verifier=None
try:
 policy=build(root);sys.path=[str(root)];standard(MiniPatch);binding._CODE_OWNED_ARTIFACT_POLICY=policy
 verifier=binding._load_code_owned_settlement_verifier();importer=binding._CODE_OWNED_IMPORTER
 relative=policy.extension_paths[0];path=root.joinpath(*relative.split('/'));replacement=root/'replacement.pyd';replacement.write_bytes(b'inert replacement bytes')
 try:path.write_bytes(b'changed')
 except OSError as e:overwrite=type(e).__name__+':'+str(getattr(e,'winerror',None))
 else:overwrite='unexpected-success'
 try:os.replace(replacement,path)
 except OSError as e:rename=type(e).__name__+':'+str(getattr(e,'winerror',None))
 else:rename='unexpected-success'
 print('pyd_overwrite_attempt='+overwrite);print('pyd_replace_attempt='+rename)
 print('retained_pyd_bytes='+importer.artifact.custody.read(relative).decode('ascii'))
 assert overwrite.startswith('PermissionError:') and rename=='PermissionError:32'
finally:
 if importer:
  try:importer.close_after_failure()
  except:pass
 if verifier and verifier._artifact.custody:
  try:verifier._artifact.custody.close()
  except:pass
 binding._CODE_OWNED_IMPORTER=None;binding._CODE_OWNED_VERIFIER_CACHE=None;binding._CODE_OWNED_ARTIFACT_POLICY=original_policy
 for name in tuple(sys.modules):
  if name=='bt_api_ctp' or name.startswith('bt_api_ctp.'):sys.modules.pop(name,None)
 sys.path,sys.meta_path,sys.path_hooks,sys.path_importer_cache=original_path,original_meta,original_hooks,original_cache
 shutil.rmtree(root,ignore_errors=True)

