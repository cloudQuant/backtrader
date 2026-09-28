import importlib, json, os, pathlib, socket, sys
import sitecustomize
mod=importlib.import_module('backtrader.stores.btapistore')
root=pathlib.Path(os.environ['R2D_EXPECTED_ROOT']).resolve()
origin=pathlib.Path(mod.__file__).resolve()
if root not in origin.parents: raise SystemExit('wrong_origin '+str(origin))
blocked=[]
for name,fn in [('bt_api_py',lambda: importlib.import_module('bt_api_py')),('_ctp',lambda: importlib.import_module('_ctp')),('dns',lambda:socket.getaddrinfo('127.0.0.1',1)),('socket_connect',lambda:socket.socket().connect(('127.0.0.1',1)))]:
    try: fn()
    except AssertionError: blocked.append(name)
    else: raise SystemExit('tripwire_not_active '+name)
if any(n.split('.',1)[0] in {'bt_api_py','_ctp'} for n in sys.modules): raise SystemExit('forbidden_module_loaded')
print(json.dumps({'store_module_origin':str(origin),'sitecustomize_origin':str(pathlib.Path(sitecustomize.__file__).resolve()),'blocked_probes':blocked,'forbidden_modules_loaded':False},sort_keys=True))
