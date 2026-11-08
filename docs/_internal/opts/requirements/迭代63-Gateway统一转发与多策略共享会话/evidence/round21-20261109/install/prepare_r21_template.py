from pathlib import Path
T=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G');P=Path('/tmp/iter63-r21-primary')
p=T/'prepare.py';s=p.read_text().replace('expected R20 runtime missing','expected R21 runtime missing')
s=s.replace("           'gateway':'ecb98a0d1f598dc33ae112829dc958a60846058b',\n",'')
s=s.replace("for name in ('base','gateway','ctp','bt'):","for name in ('base','ctp','bt'):")
s=s.replace("     'bt_api_gateway-':'eca010352ae5bd4d1c9f134a70b5627641bde80d8b8af3add437fa29cfb67a30',\n",'')
p.write_text(s)
p=T/'capture_selectors.py';s=p.read_text().replace("T/'source-runner/selectors.json'", "Path('/tmp/iter63-r21-primary/selectors.json')").replace("set(plans) != {'sdk'}","set(plans) != {'gateway', 'sdk'}");p.write_text(s)
p=T/'run.py';s=p.read_text().replace("import json\n", "import hashlib\nimport json\nimport time\n",1).replace("KINDS = ('sdk',)","KINDS = ('gateway', 'sdk')")
s=s.replace("for kind in ('sdk',):", "for kind in ('gateway', 'sdk'):").replace("for kind in ('sdk',)]])", "for kind in ('gateway', 'sdk')]])").replace('if len(wheels) != 6:', 'if len(wheels) != 5:').replace('expected six fixed wheels before build','expected five fixed wheels before build').replace('expected six fixed and one rebuilt wheel','expected five fixed and two rebuilt wheels')
s=s.replace("    started = datetime.now(timezone.utc).isoformat()\n    with log.open('wb') as output:\n        completed = subprocess.run(command, cwd=T, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)", """    run_id = name+'-'+str(os.getpid())+'-'+str(time.time_ns())
    env['R21_ORIGIN_RUN'] = run_id
    selector = T/'selectors.json'
    selector_sha = hashlib.sha256(selector.read_bytes()).hexdigest() if selector.is_file() else None
    started = datetime.now(timezone.utc).isoformat()
    header = {'run_id':run_id,'launcher_pid':os.getpid(),'launcher_ppid':os.getppid(),
              'selector_sha256':selector_sha,'argv':command,'stage':name}
    with log.open('wb') as output:
        output.write(('RUN_METADATA '+json.dumps(header,sort_keys=True)+'\\n').encode())
        output.flush()
        completed = subprocess.run(command, cwd=T, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
        output.write(('RUN_EXIT '+str(completed.returncode)+'\\n').encode())""")
s=s.replace("record = {'stage': name, 'argv': command", "record = {'run_id': run_id, 'launcher_pid':os.getpid(), 'launcher_ppid':os.getppid(), 'selector_sha256':selector_sha, 'stage': name, 'argv': command")
s=s.replace("print(name, 'exit', completed.returncode, 'log', log, flush=True)", "print(name, 'exit', completed.returncode, 'run_id',run_id,'log', log, flush=True)")
p.write_text(s)
p=T/'run_installed.py';s=p.read_text().replace("    os.environ['R21_ORIGIN_RUN'] = kind+'-'+str(os.getpid())+'-'+str(time.time_ns())", "    os.environ.setdefault('R21_ORIGIN_RUN',kind+'-'+str(os.getpid())+'-'+str(time.time_ns()))")
s=s.replace("    print('ORIGIN_RUN_LOGS',", "    print('RUN_ID',os.environ['R21_ORIGIN_RUN'],'PID',os.getpid(),'PPID',os.getppid(),flush=True)\n    print('ORIGIN_RUN_LOGS',")
p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("'REBUILT' if staged == 'sdk' else 'REUSED_R19'", "'REBUILT' if staged in {'gateway','sdk'} else 'REUSED_R19'")
s=s.replace("('back_trader_python-', 'bt_api_base-', 'bt_api_gateway-', 'bt_api_ctp-')", "('back_trader_python-', 'bt_api_base-', 'bt_api_ctp-')")
p.write_text(s)
for p in [T/'bootstrap/origin_guard.py',P/'bootstrap/origin_guard.py']:
    s=p.read_text();s=s.replace("'pid': os.getpid(), 'data': data", "'pid': os.getpid(), 'ppid': os.getppid(), 'run_id': os.environ.get('R21_ORIGIN_RUN', 'unbound'), 'data': data")
    s=s.replace("'pid':os.getpid(),'data':data", "'pid':os.getpid(),'ppid':os.getppid(),'run_id':os.environ.get('R21_ORIGIN_RUN','unbound'),'data':data")
    p.write_text(s)
p=P/'run.py';s=p.read_text().replace('import json\n','import hashlib\nimport json\n',1).replace("if KIND != 'sdk':", "if KIND not in {'gateway','sdk'}:")
s=s.replace("os.environ['R21_ORIGIN_RUN']=KIND+'-'+str(os.getpid())+'-'+str(time.time_ns())", "os.environ.setdefault('R21_ORIGIN_RUN',KIND+'-'+str(os.getpid())+'-'+str(time.time_ns()))")
s=s.replace("    print('SOURCE_ROOT',KIND,ROOT,'SELECTORS',plan,flush=True)", "    print('RUN_METADATA',json.dumps({'run_id':os.environ['R21_ORIGIN_RUN'],'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'argv':sys.orig_argv,'origin_log_group':os.environ['R21_ORIGIN_RUN']},sort_keys=True),flush=True)\n    print('SOURCE_ROOT',KIND,ROOT,'SELECTORS',plan,flush=True)")
s=s.replace("if __name__=='__main__':\n    raise SystemExit(main())", """if __name__=='__main__':
    started=time.time_ns(); code=1
    try:
        code=main()
    finally:
        plan=Path(os.environ.get('R21_SELECTORS',str(OUT/'selectors.json')))
        record={'run_id':os.environ['R21_ORIGIN_RUN'],'pid':os.getpid(),'ppid':os.getppid(),
                'kind':KIND,'argv':sys.orig_argv,'selector_sha256':hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else None,
                'started_ns':started,'finished_ns':time.time_ns(),'exit_code':code}
        with (OUT/'source-executions.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(record,sort_keys=True)+'\\n')
        print('RUN_EXIT',code,'RUN_ID',os.environ['R21_ORIGIN_RUN'],flush=True)
    raise SystemExit(code)""")
p.write_text(s)
print('R21 dual package drafts and same-run origin tracking written')
