import importlib.abc,sys
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='bt_api_ctp.ctp._ctp': raise ImportError('offline synthetic native fixture')
def install():
 if not any(isinstance(x,NoNative) for x in sys.meta_path): sys.meta_path.insert(0,NoNative())
