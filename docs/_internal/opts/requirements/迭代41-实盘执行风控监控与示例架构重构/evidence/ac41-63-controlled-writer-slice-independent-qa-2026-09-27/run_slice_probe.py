from __future__ import annotations
import ast, builtins, hashlib, importlib, io, json, os, sys, types
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(os.environ["QA_SOURCE_ROOT"]).resolve()
MODE = os.environ.get("QA_MODE", "main")
STORE_PATH = ROOT / "backtrader" / "stores" / "btapistore.py"
source_bytes = STORE_PATH.read_bytes()
source_text = source_bytes.decode("utf-8")
source_ast = ast.parse(source_text, filename=str(STORE_PATH))
results = {"mode": MODE, "source_root": str(ROOT), "btapistore_sha256": hashlib.sha256(source_bytes).hexdigest().upper(), "probes": []}
def record(name, outcome, **facts): results["probes"].append({"name": name, "outcome": outcome, **facts})
class ProbeStop(BaseException): pass
class TrapProfile:
    def __init__(self, reads): self.reads = reads
    def __getattr__(self, name):
        self.reads.append(name)
        raise AssertionError("profile attribute read before dispatch gate: " + name)
class FakeGatewayClient:
    calls = []
    def submit_order(self, payload):
        type(self).calls.append(("submit", sorted(payload)))
        raise ProbeStop("fake gateway submit boundary")
    def cancel_order(self, order_ref, dataname=None):
        type(self).calls.append(("cancel", order_ref, dataname))
        raise ProbeStop("fake gateway cancel boundary")
def class_node(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == name: return n
    raise LookupError(name)
def function_node(tree, cls, name):
    c=class_node(tree, cls)
    for n in ast.walk(c):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name: return n
    raise LookupError((cls,name))
def module_function_node(tree, name):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name: return n
    raise LookupError(name)
def compile_node(node, namespace):
    n=ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[]))
    exec(compile(n, str(STORE_PATH), "exec"), namespace)
    return namespace[node.name]
def fake_gateway_methods():
    cls=class_node(source_ast, "CtpGatewayClientWrapper")
    methods={n.name:n for n in cls.body if isinstance(n, ast.FunctionDef)}
    return methods["submit_order"],methods["create_order"],methods["cancel_order"]
def trap_gateway(label):
    submit_node,create_node,cancel_node=fake_gateway_methods()
    ns={}
    submit_fn=compile_node(submit_node,ns); create_fn=compile_node(create_node,ns); cancel_fn=compile_node(cancel_node,ns)
    obj=SimpleNamespace(_client=FakeGatewayClient())
    obj.submit_order=MethodType(submit_fn,obj)
    FakeGatewayClient.calls=[]
    try: submit_fn(obj,{"data_name":"fake-only"})
    except ProbeStop: submit=True
    else: submit=False
    try: create_fn(obj,data_name="fake-only")
    except ProbeStop: create=True
    else: create=False
    try: cancel_fn(obj,"fake-ref",dataname="fake-only")
    except ProbeStop: cancel=True
    else: cancel=False
    record(label + " gateway wrapper direct methods", "FAKE_BOUNDARY_TRAPPED" if submit and create and cancel else "FAIL",
           fake_calls=[x[0] for x in FakeGatewayClient.calls], methods_from_frozen_ast=True, no_sdk_import=True)

def fake_store_method_calls(label, actor_only=False):
    # Compile the exact frozen BtApiStore methods and bind them to an inert shell.
    global_ns={"BtApiStoreError":RuntimeError}
    public_submit=compile_node(function_node(source_ast,"BtApiStore","submit_order"),global_ns)
    legacy_submit=compile_node(function_node(source_ast,"BtApiStore","_submit_order_legacy"),global_ns)
    public_cancel=compile_node(function_node(source_ast,"BtApiStore","cancel_order"),global_ns)
    legacy_cancel=compile_node(function_node(source_ast,"BtApiStore","_cancel_order_ref_legacy"),global_ns)
    managed_submit=compile_node(function_node(source_ast,"BtApiStore","_submit_ctp_managed_order"),global_ns)
    managed_cancel=compile_node(function_node(source_ast,"BtApiStore","_cancel_managed"),global_ns)
    calls=[]
    class FakeAPI:
        def submit_order(self,payload): calls.append("fake-api.submit_order"); raise ProbeStop("fake API submit trap")
        def cancel_order(self,order_ref,dataname=None): calls.append("fake-api.cancel_order"); raise ProbeStop("fake API cancel trap")
    class Shell:
        def __init__(self):
            self._managed_execution_adapter=None
            self._sdk_mode=False
            self._candidate_actor_only=actor_only
            self._api=FakeAPI()
            self._ensure_api_ready=lambda:self._api
            self._order_to_payload=lambda order:{"marker":"fake-only"}
            self._extract_dataname=lambda data:None
            self.emit_runtime_event=lambda *a,**k:None
        def _is_ctp_session_provider(self): return True
    shell=Shell()
    shell._submit_order_legacy=MethodType(legacy_submit,shell)
    shell._cancel_order_ref_legacy=MethodType(legacy_cancel,shell)
    order=SimpleNamespace(ref="fake-ref",info={},data=None)
    if actor_only:
        cases=[]
        for name,call in (("direct _submit_order_legacy",lambda:shell._submit_order_legacy(order)),
                          ("direct _cancel_order_ref_legacy",lambda:shell._cancel_order_ref_legacy("fake-ref")),
                          ("direct _submit_ctp_managed_order",lambda:managed_submit(shell,order,object())),
                          ("direct _cancel_managed",lambda:managed_cancel(shell,"fake-ref"))):
            try: call()
            except RuntimeError as e: cases.append((name,"BLOCKED",str(e)))
            except ProbeStop: cases.append((name,"FAKE_BOUNDARY_REACHED",None))
            else: cases.append((name,"RETURNED",None))
        record(label+" actor-only internal legacy methods", "BLOCKED_AT_METHOD_ENTRY" if all(c[1]=="BLOCKED" for c in cases) else "FAIL",
               cases=cases, methods_from_frozen_ast=True, api_boundary_calls=calls)
        return
    cases=[]
    for name,call in (("public submit_order",lambda:public_submit(shell,order)),
                      ("direct private _submit_order_legacy",lambda:shell._submit_order_legacy(order)),
                      ("public cancel_order",lambda:public_cancel(shell,order)),
                      ("direct private _cancel_order_ref_legacy",lambda:shell._cancel_order_ref_legacy("fake-ref",None))):
        try: call()
        except ProbeStop as e: cases.append((name,"FAKE_BOUNDARY_REACHED",str(e)))
        else: cases.append((name,"NOT_TRAPPED",None))
    record(label+" public and private CTP legacy methods", "FAKE_BOUNDARIES_REACHED" if all(c[1]=="FAKE_BOUNDARY_REACHED" for c in cases) else "FAIL",
           cases=cases, api_boundary_calls=calls, methods_from_frozen_ast=True, no_provider_io=True)

if MODE == "main":
    sys.path.insert(0,str(ROOT))
    import backtrader_runtime.cli as cli
    from backtrader_runtime.errors import RuntimeConfigError
    from backtrader_runtime import runner
    record("runtime module provenance","EXACT_FROZEN_TREE" if Path(cli.__file__).resolve().is_relative_to(ROOT) and Path(runner.__file__).resolve().is_relative_to(ROOT) else "FAIL",
           cli=str(Path(cli.__file__).resolve()),runner=str(Path(runner.__file__).resolve()))
    private_dir=ROOT/"examples"/"013_3_sa_midfreq_simnow"/"runtime-ctp-private"
    protected_config=private_dir/"config.yaml"
    opened=[]
    original_builtin_open,original_io_open=builtins.open,io.open
    def is_protected(p):
        try: value=os.path.normcase(os.path.abspath(os.fspath(p)))
        except TypeError:return False
        base=os.path.normcase(os.path.abspath(str(private_dir)))+os.sep
        return value.startswith(base) or value==os.path.normcase(os.path.abspath(str(protected_config)))
    def guard_open(p,*a,**k):
        if is_protected(p): opened.append(os.fspath(p)); raise AssertionError("private config open attempted")
        return original_builtin_open(p,*a,**k)
    def guard_io_open(p,*a,**k):
        if is_protected(p): opened.append(os.fspath(p)); raise AssertionError("private config open attempted")
        return original_io_open(p,*a,**k)
    def forbidden(*a,**k): raise AssertionError("CLI crossed CTP preflight gate")
    stderr,stdout=io.StringIO(),io.StringIO()
    with patch.object(cli,"validate_runtime_config",forbidden), patch.object(cli,"dispatch_registered_ctp_simnow_readonly_preflight",forbidden), \
         patch.object(builtins,"open",guard_open), patch.object(io,"open",guard_io_open):
        exit_code=cli.main(["preflight","--strategy-dir",str(private_dir)],registry=cli.default_runtime_registry(),environ={},stdout=stdout,stderr=stderr)
    payload=json.loads(stderr.getvalue())
    sdk_modules=sorted(n for n in sys.modules if n.startswith(("bt_api_py","bt_api_ctp","ctp")))
    record("default registered CTP private preflight","REJECTED_BEFORE_CONFIG_OR_PROVIDER" if exit_code==2 and payload.get("reason")=="ctp_simnow_preflight_supervisor_required" and not opened and not sdk_modules else "FAIL",
           exit_code=exit_code,reason=payload.get("reason"),protected_open_attempts=len(opened),sdk_modules_loaded=sdk_modules)
    # Runner gates against inert EffectiveRuntimeConfig doubles; profile properties/import are traps.
    imports=[]
    def import_trap(name,*a,**k): imports.append(name); raise AssertionError("runner import before gate")
    gate_cases=[]
    for label,mode,available in (("live-profile","live",True),("unavailable-sandbox","simulation",False)):
        reads=[]; profile=TrapProfile(reads)
        resolved=SimpleNamespace(registration=object(),profile=profile,mode=mode,profile_dispatch_available=available)
        with patch.object(runner,"resolve_runner_effective_config",lambda *a,**k:resolved), patch.object(runner.importlib,"import_module",import_trap):
            try: runner.dispatch_registered_runtime(object(),object())
            except RuntimeConfigError: rejected=True
            else: rejected=False
        gate_cases.append((label,rejected,reads))
    record("registered runner dynamic import gates","REJECTED_BEFORE_IMPORT" if all(x[1] and not x[2] for x in gate_cases) and not imports else "FAIL",
           cases=gate_cases,import_attempts=imports)
    # Exact main Store routing methods with a synthetic environment only.
    env_values={"BT_STORE_PROVIDER":"okx_gateway","BT_GATEWAY_EXCHANGE_TYPE":"BINANCE"}
    class RouteEnv:
        reads=[]
        def get(self,key,default=None):
            self.reads.append(key); return env_values.get(key,default)
    route_env=RouteEnv(); route_ns={"os":SimpleNamespace(environ=route_env),"_GATEWAY_PROVIDERS":frozenset({"gateway","ctp_gateway","mt5_gateway"}),"_BACKENDS":frozenset({"direct","gateway","forwarding"})}
    gateway_fn=compile_node(module_function_node(source_ast,"_is_gateway_provider"),route_ns)
    backend_fn=compile_node(module_function_node(source_ast,"_resolve_backend"),route_ns)
    resolve_provider=compile_node(function_node(source_ast,"BtApiStore","_resolve_provider"),route_ns)
    apply_overrides=compile_node(function_node(source_ast,"BtApiStore","_apply_env_gateway_overrides"),route_ns)
    is_ctp=compile_node(function_node(source_ast,"BtApiStore","_is_ctp_session_provider"),route_ns)
    route_shell=SimpleNamespace(provider=None,backend=None,_api_kwargs={},_config={})
    route_shell._resolve_provider=MethodType(resolve_provider,route_shell)
    route_shell._apply_env_gateway_overrides=MethodType(apply_overrides,route_shell)
    route_shell._is_ctp_session_provider=MethodType(is_ctp,route_shell)
    route_shell.provider=route_shell._resolve_provider("ctp")
    route_shell.backend=backend_fn(route_shell.provider,None)
    route_shell._apply_env_gateway_overrides()
    route_is_ctp=route_shell._is_ctp_session_provider()
    record("synthetic environment provider/exchange rewrite","RECLASSIFIED_TO_NON_CTP" if route_shell.provider=="okx_gateway" and route_shell._api_kwargs.get("exchange_type")=="BINANCE" and not route_is_ctp else "UNEXPECTED",
           initial_provider="ctp", resolved_provider=route_shell.provider, backend=route_shell.backend, resolved_exchange=route_shell._api_kwargs.get("exchange_type"), final_ctp_classification=route_is_ctp, env_keys_read=route_env.reads, synthetic_values_only=True, no_client_or_writer_called=True)
    fake_store_method_calls("main",False)
    trap_gateway("main")
    # exact _resolve_bt_api_client source function; monkeypatched import blocks before loading bt_api_py.
    resolve_ns={"ImportError":ImportError,"BtApiMissingDependencyError":RuntimeError,"_safe_log":lambda *a,**k:None}
    resolve_fn=compile_node(module_function_node(source_ast,"_resolve_bt_api_client"),resolve_ns)
    import_calls=[]
    def stop_import(name,*a,**k): import_calls.append(name); raise ImportError("inert QA import block")
    resolve_ns["importlib"]=SimpleNamespace(import_module=stop_import)
    try: resolve_fn("ctp")
    except RuntimeError: blocked=True
    else: blocked=False
    record("lazy CTP SDK resolver","BLOCKED_AT_IMPORT_BOUNDARY" if blocked and import_calls==["bt_api_py"] else "FAIL",attempted_module_names=import_calls)
    # Record constructor source order as static evidence; actual credentials/env are never read.
    ctor=function_node(source_ast,"BtApiStore","__init__")
    relevant=[]
    for node in ast.walk(ctor):
        if isinstance(node,ast.Call):
            name=ast.unparse(node.func)
            if name in {"self._resolve_provider","require_managed_execution_adapter","self._apply_env_gateway_overrides","os.environ.get","getattr","require_ctp_runtime_execution_adapter","self._is_ctp_session_provider"}:
                relevant.append((node.lineno,name))
    relevant.sort()
    record("CTP constructor gate ordering","STATIC_PRE_GATE_ATTRIBUTE_AND_ENV_READS",source_order=relevant,
           notes="Exact main source shows initial generic adapter getter; config/environment auth reads and api.exchange_kwargs lookup precede typed CTP adapter validation. No environment/config values accessed in this probe.")
elif MODE == "r2a":
    sys.path.insert(0,str(ROOT))
    import backtrader.stores.btapistore as live_storemod
    class BlockEnv:
        reads=[]
        def get(self,key,default=None): self.reads.append(key); raise AssertionError("r2a explicit CTP gate read route env: "+key)
    class ObjectTrap:
        def __init__(self): self.reads=[]
        def __getattr__(self,name): self.reads.append(name); raise AssertionError("r2a explicit CTP gate traversed caller object: "+name)
        def __bool__(self): self.reads.append("__bool__"); raise AssertionError("r2a explicit CTP gate tested caller object")
        def __iter__(self): self.reads.append("__iter__"); raise AssertionError("r2a explicit CTP gate iterated caller object")
    block_env=BlockEnv(); trap=ObjectTrap(); original_os=live_storemod.os; live_storemod.os=SimpleNamespace(environ=block_env)
    try:
        try: live_storemod.BtApiStore(provider="ctp",api=trap,api_cls=trap,config=trap,managed_execution_adapter=trap,autostart=True)
        except live_storemod.BtApiStoreError as e: constructor_rejected=str(e)=="external account actor unavailable"
        else: constructor_rejected=False
    finally: live_storemod.os=original_os
    record("r2a explicit CTP constructor order","REJECTED_BEFORE_ENV_OR_OBJECT_READ" if constructor_rejected and not block_env.reads and not trap.reads else "FAIL",
           error="external account actor unavailable" if constructor_rejected else "unexpected", env_reads=block_env.reads, caller_object_reads=trap.reads, provider_api_not_constructed=True)
    fake_store_method_calls("r2a",True)
    trap_gateway("r2a")
else: raise SystemExit("QA_MODE must be main or r2a")
print(json.dumps(results,ensure_ascii=False,sort_keys=True,indent=2))





