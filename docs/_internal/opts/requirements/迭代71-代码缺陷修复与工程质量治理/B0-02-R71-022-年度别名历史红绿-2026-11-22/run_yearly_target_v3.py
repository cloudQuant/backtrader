import os, sys, pathlib, json
root=pathlib.Path(__file__).resolve().parent
version=sys.argv[1]
if version not in ('old','fixed'): raise ValueError('invalid version')
prefix=pathlib.Path(sys.base_prefix)
win=pathlib.Path(os.environ.get('SystemRoot',r'C:\Windows'))
(root/('mpl_'+version)).mkdir(exist_ok=True)
os.environ.clear()
os.environ.update({'SystemRoot':str(win),'WINDIR':str(win),'PATH':os.pathsep.join([str(prefix),str(prefix/'Library'/'bin'),str(win/'System32')]),'TEMP':str(root),'TMP':str(root),'MPLCONFIGDIR':str(root/('mpl_'+version)),'MPLBACKEND':'Agg','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONDONTWRITEBYTECODE':'1'})
roots=[root,prefix/'Lib',prefix/'DLLs',prefix/'Library'/'bin',win/'System32',win/'Fonts']
roots=[os.path.normcase(os.path.realpath(str(p))) for p in roots]
denied={};details=[]
def block(kind):
 denied[kind]=denied.get(kind,0)+1
 frame=sys._getframe(1);stack=[]
 while frame is not None and len(stack)<8:
  stack.append(str(frame.f_globals.get('__name__','?'))+':'+frame.f_code.co_name)
  frame=frame.f_back
 details.append({'category':kind,'stack':stack})
 raise PermissionError('public-review guard '+kind)
def allowed(path,write=False):
 if path is None:return True
 if isinstance(path,int):return True
 try: path=os.path.normcase(os.path.realpath(os.fsdecode(path)))
 except (TypeError,ValueError):return False
 if any(x.lower() in ('.env','config.yaml','config.yml','credentials','secrets','.codex') for x in pathlib.PureWindowsPath(path).parts):return False
 for parent in (roots[:1] if write else roots):
  try:
   if os.path.commonpath([path,parent])==parent:return True
  except ValueError:pass
 return False
def audit(event,args):
 if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.spawn','os.exec','_winapi.CreateProcess'):block('network_or_process')
 if event in ('os.listdir','os.scandir') and args and not allowed(args[0]):block('directory_read')
 if event=='open':
  path=args[0];mode=args[1] if len(args)>1 else None;flags=args[2] if len(args)>2 else 0
  write=isinstance(mode,str) and any(x in mode for x in 'wax+')
  if isinstance(flags,int):write=write or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if not allowed(path,write):block('file_write' if write else 'file_read')
sys.addaudithook(audit)
try:open('C:/Users/yunji/.codex/review_guard_nonexistent','rb')
except PermissionError:print('PRIVATE_READ_SELFTEST OK',flush=True)
else:raise RuntimeError('guard selftest failed')
denied.clear();details.clear()
os.chdir(str(root))
sys.path[:0]=[str(root/version),str(prefix/'Lib'/'site-packages')]
import socket
socket.gethostname=lambda:'synthetic-review-host'
import pandas,matplotlib,pytest,backtrader
import backtrader.reports.charts as charts
if os.path.commonpath([os.path.realpath(charts.__file__),os.path.realpath(str(root/version))]) != os.path.realpath(str(root/version)):raise RuntimeError('source origin mismatch')
print('VERSIONS',sys.version.split()[0],pandas.__version__,matplotlib.__version__,pytest.__version__,flush=True)
print('SOURCE_ORIGIN',charts.__file__,flush=True)
test=root/'test_yearly_target_v2.py'
args=['-s','--noconftest','-p','no:cacheprovider','-o','addopts=','--log-file='+str(root/('pytest_target_v3_'+version+'.log')),'--basetemp='+str(root/('pytest_target_v3_'+version+'_tmp')),'-q','--tb=short',str(test)]
status=pytest.main(args)
(root/('receipt_target_v3_'+version+'.json')).write_text(json.dumps({'status':int(status),'denied':denied,'details':details,'source':str(charts.__file__)},sort_keys=True),encoding='utf-8')
raise SystemExit(status)
