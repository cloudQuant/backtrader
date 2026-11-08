"""Check both guards reject outside origins and retain missing-module semantics."""
import importlib.util
import os
from pathlib import Path
import tempfile

os.environ['R17_ORIGIN_RUN'] = 'guard-semantics-preflight'
paths = (
    Path('/tmp/iter63-r17-primary/bootstrap/origin_guard.py'),
    Path('/tmp/iter63-r17-install-20261109-oNtWsjp3/bootstrap/origin_guard.py'),
)
with tempfile.TemporaryDirectory(prefix='r17-guard-preflight-') as directory:
    outside = Path(directory)
    (outside/'spoof.py').write_text('value=1\n')
    for index, path in enumerate(paths):
        spec = importlib.util.spec_from_file_location(f'r17_origin_preflight_{index}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        finder = module.SourceFinder() if index == 0 else module.TargetFinder()
        try:
            finder.find_spec('bt_api_base.absent_for_preflight', [str(outside)])
        except ModuleNotFoundError as exc:
            assert exc.name == 'bt_api_base.absent_for_preflight'
        else:
            raise AssertionError('missing module not reported with canonical name')
        try:
            finder.find_spec('bt_api_base.spoof', [str(outside)])
        except ImportError as exc:
            assert not isinstance(exc, ModuleNotFoundError)
        else:
            raise AssertionError('outside project origin accepted')
        print('GUARD_MISSING_AND_OUTSIDE_ORIGIN_OK', path, flush=True)
