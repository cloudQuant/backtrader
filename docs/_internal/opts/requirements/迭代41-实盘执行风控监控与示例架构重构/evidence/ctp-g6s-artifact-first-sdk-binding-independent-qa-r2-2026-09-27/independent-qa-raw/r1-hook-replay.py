import importlib.machinery, os, runpy, shutil, sys, tempfile
from pathlib import Path
ns=runpy.run_path(str(Path('tests/unit/runtime/test_ctp_sdk_artifact_binding.py')))
binding=ns['binding']; readiness=ns['readiness']; build=ns['_build_fake_distribution']; standard=ns['_use_standard_import_chain']
class MiniPatch:
 @staticmethod
 def setattr(obj,name,value):setattr(obj,name,value)
old_path,old_meta,old_hooks,old_cache=sys.path,sys.meta_path,sys.path_hooks,sys.path_importer_cache
old_loader=importlib.machinery.ExtensionFileLoader;old_policy=binding._CODE_OWNED_ARTIFACT_POLICY
root=Path(os.environ['USERPROFILE'])/'Temp'/('iter41-r1-replay-'+next(tempfile._get_candidate_names()));root.mkdir();calls=[];importer=verifier=None
class InertReplacementLoader:
 def __init__(self,*args,**kwargs):calls.append('constructed')
 def create_module(self,*args,**kwargs):calls.append('create_module')
 def exec_module(self,*args,**kwargs):calls.append('exec_module')
try:
 policy=build(root);sys.path=[str(root)];standard(MiniPatch);binding._CODE_OWNED_ARTIFACT_POLICY=policy
 readiness.require_trusted_ctp_sdk_artifact_before_client();importer=binding._CODE_OWNED_IMPORTER;verifier=binding._CODE_OWNED_VERIFIER_CACHE
 importlib.machinery.ExtensionFileLoader=InertReplacementLoader
 try:importer._spec_for('bt_api_ctp.ctp._ctp')
 except binding.CtpSdkArtifactBindingError as exc:reason=exc.reason
 else:reason='unexpected-accepted'
 print('r1_sequence_result='+reason)
 print('replacement_loader_calls='+str(len(calls)))
 print('actual_pyd_loaded=false')
 assert reason=='sdk_artifact_importlib_machinery_changed' and not calls
finally:
 importlib.machinery.ExtensionFileLoader=old_loader
 if importer:
  try: importer.close_after_failure()
  except: pass
 if verifier and verifier._artifact.custody:
  try: verifier._artifact.custody.close()
  except: pass
 binding._CODE_OWNED_IMPORTER=None;binding._CODE_OWNED_VERIFIER_CACHE=None;binding._CODE_OWNED_ARTIFACT_POLICY=old_policy
 for name in tuple(sys.modules):
  if name=='bt_api_ctp' or name.startswith('bt_api_ctp.'):sys.modules.pop(name,None)
 sys.path,sys.meta_path,sys.path_hooks,sys.path_importer_cache=old_path,old_meta,old_hooks,old_cache
 shutil.rmtree(root,ignore_errors=True)
