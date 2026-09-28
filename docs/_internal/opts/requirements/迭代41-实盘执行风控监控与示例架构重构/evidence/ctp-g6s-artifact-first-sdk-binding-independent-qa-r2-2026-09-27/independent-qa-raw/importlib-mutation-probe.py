import importlib.machinery
import importlib.util
import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ns = runpy.run_path(str(Path('tests/unit/runtime/test_ctp_sdk_artifact_binding.py')))
binding = ns['binding']; readiness = ns['readiness']
build_fake = ns['_build_fake_distribution']; use_standard = ns['_use_standard_import_chain']
class MiniPatch:
    @staticmethod
    def setattr(obj, name, value): setattr(obj, name, value)
attacks = [
    ('ExtensionFileLoader', importlib.machinery, 'ExtensionFileLoader'),
    ('ModuleSpec', importlib.machinery, 'ModuleSpec'),
    ('module_from_spec', importlib.util, 'module_from_spec'),
    ('PathFinder.find_spec', importlib.machinery.PathFinder, 'find_spec'),
]
for label, target, attribute in attacks:
    old_path, old_meta, old_hooks, old_cache = sys.path, sys.meta_path, sys.path_hooks, sys.path_importer_cache
    old_policy = binding._CODE_OWNED_ARTIFACT_POLICY
    old_value = getattr(target, attribute)
    root = Path(os.environ['USERPROFILE'])/'Temp'/('iter41-r2-mutation-'+next(tempfile._get_candidate_names()))
    root.mkdir(); calls = []; importer = verifier = None
    def replacement(*args, **kwargs):
        calls.append('called')
        return None
    try:
        policy = build_fake(root)
        sys.path = [str(root)]; use_standard(MiniPatch)
        binding._CODE_OWNED_ARTIFACT_POLICY = policy
        readiness.require_trusted_ctp_sdk_artifact_before_client()
        setattr(target, attribute, replacement)
        try:
            binding._get_preclient_code_owned_verifier()
        except binding.CtpSdkArtifactBindingError as exc:
            reason = exc.reason
        else:
            reason = 'unexpected-accepted'
        importer = binding._CODE_OWNED_IMPORTER; verifier = binding._CODE_OWNED_VERIFIER_CACHE
        print(f'{label}: reason={reason}; replacement_calls={len(calls)}')
        assert reason == 'sdk_artifact_importlib_machinery_changed' and not calls
    finally:
        setattr(target, attribute, old_value)
        importer = importer or binding._CODE_OWNED_IMPORTER
        verifier = verifier or binding._CODE_OWNED_VERIFIER_CACHE
        if importer is not None:
            try: importer.close_after_failure()
            except BaseException: pass
        if verifier is not None and verifier._artifact.custody is not None:
            try: verifier._artifact.custody.close()
            except BaseException: pass
        binding._CODE_OWNED_IMPORTER = None; binding._CODE_OWNED_VERIFIER_CACHE = None
        binding._CODE_OWNED_ARTIFACT_POLICY = old_policy
        for name in tuple(sys.modules):
            if name == 'bt_api_ctp' or name.startswith('bt_api_ctp.'): sys.modules.pop(name, None)
        sys.path, sys.meta_path, sys.path_hooks, sys.path_importer_cache = old_path, old_meta, old_hooks, old_cache
        shutil.rmtree(root, ignore_errors=True)
