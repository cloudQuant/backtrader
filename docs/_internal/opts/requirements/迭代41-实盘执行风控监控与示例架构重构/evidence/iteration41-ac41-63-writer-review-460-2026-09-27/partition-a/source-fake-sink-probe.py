"""AST-extracted source control-flow check with a local fake CTP gateway sink."""
import ast,copy,hashlib,json
from pathlib import Path
ROOT=Path(r"D:\source_code\backtrader")
SOURCE=ROOT/"backtrader/stores/btapistore.py"
tree=ast.parse(SOURCE.read_text(encoding="utf-8"),filename=str(SOURCE))
factory=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_create_ctp_gateway_wrapper_class")
cls=next(n for n in factory.body if isinstance(n,ast.ClassDef) and n.name=="CtpGatewayClientWrapper")
wanted={"__init__","_is_supported_non_ctp_exchange","_ensure_direct_writes_allowed","_client","submit_order","create_order","cancel_order"}
nodes=[copy.deepcopy(n) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
if {n.name for n in nodes}!=wanted: raise SystemExit("source method extraction incomplete")
class BtApiStoreError(RuntimeError): pass
ns={"BtApiStoreError":BtApiStoreError}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(SOURCE),"exec"),ns)
Wrapper=type("ExtractedWrapper",(),{})
for name in wanted: setattr(Wrapper,name,ns[name])
class FakeGateway:
    def __init__(self): self.calls=[]
    def submit_order(self,payload):
        self.calls.append({"method":"submit_order","payload":dict(payload)})
        return {"accepted_by_fake_sink":True}
    def cancel_order(self,order_ref,dataname=None):
        self.calls.append({"method":"cancel_order","order_ref":order_ref,"dataname":dataname})
        return {"cancelled_by_fake_sink":True}
wrapper=Wrapper()
wrapper.__init__(exchange_type="CTP")
default_disabled=wrapper._direct_ctp_writes_disabled
client_lazy=wrapper._gateway_client is None
fake=FakeGateway()
wrapper._gateway_client=fake
blocked=[]
for name,invoke in (
 ("submit_order",lambda:wrapper.submit_order({"symbol":"FAKE","size":1})),
 ("create_order",lambda:wrapper.create_order(symbol="FAKE",size=1)),
 ("cancel_order",lambda:wrapper.cancel_order("fake-ref",dataname="FAKE"))):
    try: invoke()
    except BtApiStoreError: blocked.append(name)
if fake.calls: raise SystemExit("default flag reached fake sink")
wrapper._direct_ctp_writes_disabled=False
wrapper.submit_order({"symbol":"FAKE","size":1})
wrapper.create_order(symbol="FAKE",size=2)
wrapper.cancel_order("fake-ref",dataname="FAKE")
result={
 "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest().upper(),
 "method_nodes_extracted_from_current_source":sorted(wanted),
 "backtrader_or_provider_imported":False,"native_or_network_call_performed":False,
 "constructor_exchange_type":"CTP","constructor_sets_direct_writes_disabled":default_disabled,
 "gateway_client_remains_lazy_at_ctp_construction":client_lazy,
 "operations_rejected_before_fake_sink_with_default_flag":blocked,
 "fake_sink_calls_after_clearing_mutable_flag":[x["method"] for x in fake.calls],
 "interpretation":"Conditional reachability of current extracted wrapper methods only; no real provider/native/network behavior or default runtime reachability established."
}
print(json.dumps(result,indent=2,sort_keys=True))
