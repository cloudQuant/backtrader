import importlib.abc, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'bt_api_ctp.ctp._ctp':
            raise ImportError('offline synthetic native fixture')
sys.meta_path.insert(0, NoNative())
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
