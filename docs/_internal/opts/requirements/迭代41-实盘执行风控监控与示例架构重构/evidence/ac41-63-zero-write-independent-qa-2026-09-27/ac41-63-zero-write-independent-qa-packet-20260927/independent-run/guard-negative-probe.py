import importlib.util, json, os, pathlib, socket, subprocess, sys
root=pathlib.Path(sys.argv[1]).resolve(); probe_path=root/'scripts'/'probe_iteration41_zero_write_path.py'; sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('isolated_zero_write_probe',probe_path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
names=('network_attempts','process_attempts','native_import_attempts','protected_input_attempts','file_write_attempts','filesystem_mutations','blocked_writer_entry_calls','runtime_only_writer_entry_calls')
counters={name:[] for name in names}; local=[]; writes=[]; sinks=[]; process=[]
read_fd,write_fd=os.pipe()
sys.addaudithook(mod._audit_boundary(str(root),counters,local,writes,sinks,process))
results={}
def attempt(name,fn):
    try: fn(); results[name]={'blocked':False,'outcome':'returned'}
    except mod.ProbeBlockedEvent as e: results[name]={'blocked':True,'outcome':str(e)}
    except BaseException as e: results[name]={'blocked':False,'outcome':'unexpected:'+type(e).__name__}
write_path=root/'evidence'/'guard-write-negative.txt'; mkdir_path=root/'evidence'/'guard-mkdir-negative'
attempt('network_getaddrinfo',lambda:socket.getaddrinfo('localhost',9))
attempt('provider_import',lambda:__import__('bt_api_ctp'))
attempt('filesystem_open_write',lambda:open(write_path,'w',encoding='utf-8'))
attempt('filesystem_mkdir',lambda:os.mkdir(mkdir_path))
attempt('subprocess_launch',lambda:subprocess.Popen([sys.executable,'-c','raise SystemExit(0)']))
file_events_before=len(counters['file_write_attempts']);
try:
    n=os.write(write_fd,b'x'); data=os.read(read_fd,1); raw_write={'returned_bytes':n,'read_back':data.decode('ascii'),'blocked':False}
except mod.ProbeBlockedEvent as e: raw_write={'blocked':True,'outcome':str(e)}
finally:
    os.close(read_fd); os.close(write_fd)
results['direct_os_write_to_anonymous_pipe']=raw_write
results['direct_os_write_added_file_write_counter']=len(counters['file_write_attempts'])-file_events_before
results['protected_side_effects']={'write_file_exists':write_path.exists(),'mkdir_path_exists':mkdir_path.exists(),'provider_module_loaded':'bt_api_ctp' in sys.modules}
results['counters']={name:len(value) for name,value in counters.items()}
results['observed_events']={name:value for name,value in counters.items() if value}
results['guard_behavior']='representative audited Python entry points were blocked before side effect; raw os.write to an already-open anonymous pipe was not observed by this audit hook' if raw_write.get('blocked') is False else 'all tested entry points blocked'
print(json.dumps(results,indent=2,sort_keys=True))
if not all(results[n]['blocked'] for n in ('network_getaddrinfo','provider_import','filesystem_open_write','filesystem_mkdir','subprocess_launch')): raise SystemExit(2)
if results['protected_side_effects']['write_file_exists'] or results['protected_side_effects']['mkdir_path_exists'] or results['protected_side_effects']['provider_module_loaded']: raise SystemExit(3)