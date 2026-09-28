import importlib.machinery
import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ns = runpy.run_path(str(Path('tests/unit/runtime/test_ctp_sdk_artifact_binding.py')))
binding = ns['binding']
build_fake = ns['_build_fake_distribution']
use_standard_chain = ns['_use_standard_import_chain']
dist_name = 'bt_api_ctp'
original_path = sys.path
original_meta = sys.meta_path
original_hooks = sys.path_hooks
original_cache = sys.path_importer_cache
original_extension_loader = importlib.machinery.ExtensionFileLoader
original_policy = binding._CODE_OWNED_ARTIFACT_POLICY
root = Path(os.environ['USERPROFILE']) / 'Temp' / ('iter41-extension-hook-' + next(tempfile._get_candidate_names()))
root.mkdir()
importer = None
verifier = None

class MiniPatch:
    @staticmethod
    def setattr(obj, name, value):
        setattr(obj, name, value)

try:
    policy = build_fake(root)
    sys.path = [str(root)]
    use_standard_chain(MiniPatch)
    binding._CODE_OWNED_ARTIFACT_POLICY = policy
    verifier = binding._load_code_owned_settlement_verifier()
    importer = binding._CODE_OWNED_IMPORTER
    assert importer is not None and verifier._artifact.custody is not None

    class InertReplacementLoader:
        def __init__(self, fullname, path):
            self.name = fullname
            self.path = path

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.HOOK_MARKER = 'fake-loader-ran'

    # Mutate an importer global after the release gate, without changing any
    # sys.path/meta_path/path_hooks/module-cache snapshot.
    importlib.machinery.ExtensionFileLoader = InertReplacementLoader
    fullname = 'bt_api_ctp.ctp._ctp'
    spec = importer._spec_for(fullname)
    import types
    module = types.ModuleType(fullname)
    module.__spec__ = spec
    module.__file__ = spec.origin
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    assert module.HOOK_MARKER == 'fake-loader-ran'
    print('same_process_extension_loader_swap=ACCEPTED')
    print('fake_loader_marker=' + module.HOOK_MARKER)
    print('native_extension_loaded=false')
    print('retained_hash_checked_before_path_delegate=true')
finally:
    importlib.machinery.ExtensionFileLoader = original_extension_loader
    if importer is not None:
        try:
            importer.close_after_failure()
        except BaseException as exc:
            print('importer_close_error=' + type(exc).__name__)
    if verifier is not None and verifier._artifact.custody is not None:
        try:
            verifier._artifact.custody.close()
        except BaseException as exc:
            print('custody_close_error=' + type(exc).__name__)
    binding._CODE_OWNED_VERIFIER_CACHE = None
    binding._CODE_OWNED_IMPORTER = None
    binding._CODE_OWNED_ARTIFACT_POLICY = original_policy
    for name in tuple(sys.modules):
        if name == dist_name or name.startswith(dist_name + '.'):
            sys.modules.pop(name, None)
    sys.path = original_path
    sys.meta_path = original_meta
    sys.path_hooks = original_hooks
    sys.path_importer_cache = original_cache
    shutil.rmtree(root, ignore_errors=True)
