"""Readonly source-equivalence proof for the three added profiler caches."""
import hashlib
import importlib.util
import json
import marshal
import struct
import sys
import types
from pathlib import Path

ROOT=Path("D:/source_code/backtrader")
E=ROOT/"docs/_internal/opts/requirements/\u8fed\u4ee341-\u5b9e\u76d8\u6267\u884c\u98ce\u63a7\u76d1\u63a7\u4e0e\u793a\u4f8b\u67b6\u6784\u91cd\u6784/evidence"
OUT=E/"iteration41-optional16-r29-profiler-bytecode-source-proof-r1-2026-10-04"
SOURCES={
 "cProfile":(Path("C:/anaconda3/Lib/cProfile.py"),"0a97cf92d0e3efd2e08c2f9b0f0fb8e52a2b26978550804d8e59435201f3fa84"),
 "profile":(Path("C:/anaconda3/Lib/profile.py"),"4d87bdc8b85bf0a9bdee3e9d975a8a1a0c7360cb264fb68c4c48a102e718e3a3"),
 "pstats":(Path("C:/anaconda3/Lib/pstats.py"),"d62d1e6a626ebd92187419bfe075a76997cce26fe99dd4520786d4a82b6ff10c"),
}
MAX_CACHE_BYTES=2*1024*1024
CODE_FIELDS=("co_argcount","co_posonlyargcount","co_kwonlyargcount","co_nlocals","co_stacksize","co_flags","co_code","co_consts","co_names","co_varnames","co_freevars","co_cellvars","co_name","co_qualname","co_firstlineno","co_linetable","co_exceptiontable")
def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(value,reason):
 if not value:raise RuntimeError(reason)
def shape(value,depth=0,budget=None):
 if budget is None:budget=[0]
 budget[0]+=1;need(depth<128 and budget[0]<=100000,"code_graph_bound")
 t=type(value)
 if t is types.CodeType:return ("code",tuple((name,shape(getattr(value,name),depth+1,budget)) for name in CODE_FIELDS))
 if value is None:return ("none",)
 if t in (bool,int,str,bytes):return (t.__name__,value)
 if t is float:return ("float",struct.pack(">d",value))
 if t is complex:return ("complex",struct.pack(">d",value.real),struct.pack(">d",value.imag))
 if t is tuple:return ("tuple",tuple(shape(v,depth+1,budget) for v in value))
 if t is frozenset:
  items=[shape(v,depth+1,budget) for v in value]
  return ("frozenset",tuple(sorted(items,key=marshal.dumps)))
 raise RuntimeError("code_graph_constant_type")
def verify_module_cache(name,source_raw,cache_raw):
 need(name in SOURCES,"profiler_module_not_fixed")
 source_path,expected_sha=SOURCES[name]
 need(type(source_raw) is bytes and sha(source_raw)==expected_sha,"profiler_source_pin")
 need(type(cache_raw) is bytes and 16<len(cache_raw)<=MAX_CACHE_BYTES,"profiler_cache_bound")
 need(cache_raw[:4]==importlib.util.MAGIC_NUMBER,"profiler_cache_magic")
 flags=int.from_bytes(cache_raw[4:8],"little")
 need(flags in (0,1,3),"profiler_cache_flags")
 actual=marshal.loads(cache_raw[16:])
 need(type(actual) is types.CodeType,"profiler_cache_payload_not_code")
 reference=compile(source_raw,str(source_path),"exec",dont_inherit=True,optimize=0)
 expected_graph=shape(reference);actual_graph=shape(actual)
 need(actual_graph==expected_graph,"profiler_cache_source_graph_mismatch")
 return {"module":name,"source_path":str(source_path),"source_sha256":expected_sha,"source_bytes":len(source_raw),"cache_path":str(Path(importlib.util.cache_from_source(str(source_path)))),"cache_sha256":sha(cache_raw),"cache_bytes":len(cache_raw),"cache_flags":flags,"source_code_graph_equal":True,"normalized_code_graph_sha256":sha(marshal.dumps(expected_graph)),"only_code_filename_ignored":True}
def main():
 need(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and sys.flags.optimize==0,"isolated_flags")
 need(sys.version_info[:3]==(3,11,5),"fixed_compiler_version")
 rows=[];pre=[]
 for name,(source_path,pin) in SOURCES.items():
  cache_path=Path(importlib.util.cache_from_source(str(source_path)))
  source=source_path.read_bytes();cache=cache_path.read_bytes()
  rows.append(verify_module_cache(name,source,cache));pre.extend(((source_path,source),(cache_path,cache)))
 need(all(p.read_bytes()==raw for p,raw in pre),"profiler_inputs_changed")
 result={"schema":"iteration41.optional16.r29.profiler-bytecode-source-proof.v1","status":"READONLY_SOURCE_EQUIVALENCE_VERIFIED","modules":rows,"source_pre_post_bytes_equal":True,"cache_pre_post_bytes_equal":True,"profiler_imports_performed":False,"bytecode_executed":False,"sdk_imports_performed":False,"native_supervisor_or_provider_calls":False,"physical_custody_established":False,"actual_outer_must_hold_all_source_and_cache_files":True,"child_cache_origin_observed":False,"strict_cases_passed":0,"whole_command_g1":False}
 OUT.mkdir()
 raw=(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+"\n").encode("ascii")
 with (OUT/"root-observation.json").open("xb") as f:f.write(raw)
 print(json.dumps({"status":result["status"],"root_observation_sha256":sha(raw),"module_count":len(rows),"cache_pins":[{"module":r["module"],"sha256":r["cache_sha256"],"bytes":r["cache_bytes"]} for r in rows],"strict_cases_passed":0},sort_keys=True))
if __name__=="__main__":main()
