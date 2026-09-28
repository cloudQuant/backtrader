from __future__ import annotations

import importlib.machinery
import inspect
import sys

loader = importlib.machinery.ExtensionFileLoader
source = inspect.getsource(loader)
print(f"python={sys.version.split()[0]}")
print(f"implementation={sys.implementation.name}")
print(f"loader_source={inspect.getsourcefile(loader)}")
print(f"constructor={inspect.signature(loader)}")
print(f"create_module={inspect.signature(loader.create_module)}")
print(f"exec_module={inspect.signature(loader.exec_module)}")
print(f"has_path_attribute={hasattr(loader('probe', 'C:/probe.pyd'), 'path')}")
print(f"has_handle_parameter={'handle' in inspect.signature(loader).parameters}")
assert inspect.signature(loader) == inspect.Signature(
    [
        inspect.Parameter('name', inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter('path', inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ]
)
assert 'create_dynamic, spec' in source
assert 'exec_dynamic, module' in source
assert 'handle' not in inspect.signature(loader).parameters
print('result=PATH_ONLY_LOADER_SURFACE; no extension imported or loaded')
