"""R15 source-only successor glue; default disabled and parent-deadline bound."""
import hashlib
import importlib.machinery
import io
import math
import ntpath
import os
import json
import sys
import threading
import time
import types
from pathlib import Path

ROOT=Path("D:/source_code/backtrader")
E=ROOT/"docs/_internal/opts/requirements/\u8fed\u4ee341-\u5b9e\u76d8\u6267\u884c\u98ce\u63a7\u76d1\u63a7\u4e0e\u793a\u4f8b\u67b6\u6784\u91cd\u6784/evidence"
SOURCE=ROOT/"scripts/iteration41_optional16_r33_root_driver_r15.py"
SOURCE_SHA=None
TEST=ROOT/"tests/unit/scripts/test_iteration41_optional16_r33_deadline_r15.py"
TEST_SHA=None
ACTIVE_SOURCE=Path("D:/temp/iteration41-optional16-r33-root-driver-r15.py")
CU=Path("D:/temp/iteration41-root-public-custody-v2.py")
CU_SHA="e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
IMAGE=Path("D:/temp/iteration41-optional16-r29-process-image-launcher-r3.py")
IMAGE_SHA="ab139e92862e18c58ef566848c8e5809a52b3979325bc170d4f404d1dbf746a6"
PACKET=E/"iteration41-optional16-r33-root-driver-r15-source-candidate-2026-10-07"
PACKET_PINS={'source-bundle.zip': None, 'source-index.json': None, 'source-pins.json': None, 'checkpoint.json': None}
REVIEW=E/"iteration41-optional16-r33-root-driver-r15-independent-review-2026-10-07"
CONTROL=Path("D:/temp/iteration41-optional16-r33-root-held-activation-r15")
OUT=E/"iteration41-optional16-r33-root-held-invocation-r15-2026-10-07"

PROFILER_PROOF=Path("D:/temp/iteration41-r29-profiler-bytecode-source-proof-r1.py")
PROFILER_PROOF_SHA="7c7de3f15710f5f1b3fc8047bb35b50454d2ed6e5382bfb4096827dca405a913"
PROFILER_RECORD=E/"iteration41-optional16-r29-profiler-bytecode-source-proof-r1-2026-10-04/root-observation.json"
PROFILER_RECORD_SHA="0cd9bf5b246368726b495635d6a2c414e1dccb4b208c2e1a17783e7803dbfbaa"
PROFILER_CACHE_PINS={
 "C:/anaconda3/Lib/__pycache__/cProfile.cpython-311.pyc":"9d9a26a0e0aefd28a28dcd09bf97fd66072f8d537d18431f609485e16fb206b3",
 "C:/anaconda3/Lib/__pycache__/profile.cpython-311.pyc":"97408337b11e2c3b44bfb68c6e1f5e84de2536d4185049fec7038ecefc22a346",
 "C:/anaconda3/Lib/__pycache__/pstats.cpython-311.pyc":"8e66b028e50b31e7fbc7de63fcfe77025304aeb63b84e085ce13db784dca77ad",
}

ROOT_ACTUAL_ENABLED=False
ROOT_REVIEW_READY=False
ROOT_REVIEW_PINS={'review.json': None, 'review-bundle.zip': None, 'review-index.json': None, 'review-checkpoint.json': None}
ROOT_REVIEW_README_SHA=None
_ROOT_SELF_SHA256=None
_KEEPALIVE=[]
APPLICATION_WAIT_SECONDS=100.0
PARENT_DEADLINE_CLOCK_DOMAIN="windows-cpython-3.11.5-monotonic-v1"
PARENT_CAPTURE_RESERVE_SECONDS=5.0
PARENT_DEADLINE_MONOTONIC=None
PARENT_DEADLINE_DOMAIN=None
MAX_PARENT_FRAME_BYTES=64*1024
INERT_PIN_COUNT=471
ACTIVE_PIN_COUNT=481
ACTIVE_ALIAS_COUNT=16

def need(value,reason="root_public_contract"):
 if not value:raise RuntimeError(reason)

def _validated_parent_deadline(now=None):
 if (sys.platform!="win32" or sys.implementation.name!="cpython" or sys.version_info[:3]!=(3,11,5)):return None
 if now is None:now=time.monotonic()
 deadline=PARENT_DEADLINE_MONOTONIC
 if type(now) is not float or type(deadline) is not float:return None
 if PARENT_DEADLINE_DOMAIN!=PARENT_DEADLINE_CLOCK_DOMAIN:return None
 if not math.isfinite(now) or not math.isfinite(deadline):return None
 remaining=deadline-now
 if not math.isfinite(remaining) or not 0.0<remaining<=100.0:return None
 return deadline

def _bounded_application_wait(now=None):
 if now is None:now=time.monotonic()
 deadline=_validated_parent_deadline(now)
 if deadline is None:return 0.0
 if type(APPLICATION_WAIT_SECONDS) is not float or not math.isfinite(APPLICATION_WAIT_SECONDS) or not 0.0<APPLICATION_WAIT_SECONDS<=100.0:return 0.0
 remaining=deadline-now-PARENT_CAPTURE_RESERVE_SECONDS
 if not math.isfinite(remaining):return 0.0
 return min(APPLICATION_WAIT_SECONDS,max(0.0,remaining))

def _run_active_application(active,*,now=None,event_factory=None,thread_factory=None):
 """Production thread/wait seam; the outer deadline is sampled at wait time."""
 clock=now or time.monotonic
 make_event=event_factory or threading.Event
 make_thread=thread_factory or threading.Thread
 deadline=_validated_parent_deadline(clock())
 need(deadline is not None,"parent_deadline_invalid")
 active.PARENT_DEADLINE_MONOTONIC=deadline
 active.PARENT_DEADLINE_DOMAIN=PARENT_DEADLINE_CLOCK_DOMAIN
 done=make_event();state={"code":None,"error":None}
 def invoke():
  try:state["code"]=active.main([])
  except BaseException as exc:state["error"]=type(exc).__name__
  finally:done.set()
 thread=make_thread(target=invoke,name="root-r15-bounded-application",daemon=True)
 started=clock();thread.start()
 wait_seconds=_bounded_application_wait(clock())
 complete=done.wait(wait_seconds)
 if complete:thread.join(max(0.0,wait_seconds-(clock()-started)))
 return {"done":done,"state":state,"thread":thread,"started":started,
         "complete":complete,"wait_seconds":wait_seconds}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read_pin(path,digest):
 raw=Path(path).read_bytes()
 need(type(digest) is str and len(digest)==64 and sha(raw)==digest,"public_pin_mismatch")
 return raw
def load(raw,path,name):
 module=types.ModuleType(name)
 module.__file__=str(path);module.__package__="";module.__cached__=None;module.__loader__=None
 module.__spec__=importlib.machinery.ModuleSpec(name,loader=None,origin=str(path))
 module.__verified_source_sha256__=sha(raw)
 need(name not in sys.modules,"module_alias_already_used")
 sys.modules[name]=module
 exec(compile(raw,str(path),"exec",dont_inherit=True),module.__dict__)
 return module
def _held_path_key(path):
 need(isinstance(path,(str,Path)),"held_path_type")
 value=os.fspath(path)
 need(ntpath.isabs(value),"held_path_absolute_required")
 return ntpath.normcase(ntpath.normpath(value))
def _canonical_held(raw_held):
 need(type(raw_held) is dict,"held_map_type")
 canonical_map={}
 for path,raw in raw_held.items():
  need(type(raw) is bytes,"held_bytes_type")
  key=_held_path_key(path)
  need(key not in canonical_map or canonical_map[key]==raw,"held_path_alias_conflict")
  canonical_map[key]=raw
 return canonical_map
def _held_bytes(held,path):
 key=_held_path_key(path)
 need(key in held,"held_path_not_locked")
 return held[key]

def canonical(value):return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+"\n").encode("ascii")
def save_new(path,value):
 with path.open("xb") as stream:stream.write(canonical(value));stream.flush()
class BoundedSink(io.StringIO):
 def __init__(self):super().__init__();self.total=0;self.overflow=False;self.lock=threading.Lock()
 def write(self,value):
  need(type(value) is str,"parent_output_type")
  raw=value.encode("ascii","strict")
  with self.lock:
   if self.total+len(raw)>MAX_PARENT_FRAME_BYTES:
    self.overflow=True;raise RuntimeError("parent_output_limit")
   self.total+=len(raw)
   return super().write(value)

def inert_source_check():
 module=load(read_pin(SOURCE,SOURCE_SHA),SOURCE,"_root_r32_r2_inert_public_check")
 need(module.ROOT_ENABLED is False and module.ROOT_REVIEWED_ACTIVATION is False and module.ROOT_DRIVER_REVIEW_READY is False and module.ROOT_DRIVER_SHA256 is None,"disk_activation_not_unset")
 read_pin(TEST,TEST_SHA)
 for name,digest in PACKET_PINS.items():read_pin(PACKET/name,digest)
 result=module.public_check()
 need(result["activation"]=="UNSET" and type(result.get("strict_cases_passed")) is int and result["strict_cases_passed"]==0)
 return result

def main():
 args=sys.argv[1:]
 need(sys.flags.isolated==1 and sys.flags.no_site==1 and sys.dont_write_bytecode is True and sys.flags.optimize==0,"isolated_command_required")
 if args==["--source-check"]:
  print(json.dumps(inert_source_check(),sort_keys=True));return 0
 if (args and args!=["--activation-precheck"]) or ROOT_ACTUAL_ENABLED is not True or ROOT_REVIEW_READY is not True:
  print(json.dumps({"status":"PREPARED_UNSET","strict_cases_passed":0,"case_pass":False,"g1_accepted":False},sort_keys=True));return 2
 need(type(ROOT_REVIEW_PINS) is dict and set(ROOT_REVIEW_PINS)=={"review.json","review-bundle.zip","review-index.json","review-checkpoint.json"},"review_pin_shape")
 need(all(type(h) is str and len(h)==64 and all(c in "0123456789abcdef" for c in h) for h in ROOT_REVIEW_PINS.values()),"review_pin_invalid")
 need(type(_ROOT_SELF_SHA256) is str and len(_ROOT_SELF_SHA256)==64,"root_self_pin_unset")
 read_pin(Path(__file__),_ROOT_SELF_SHA256)
 need(not CONTROL.exists() and not OUT.exists(),"root_namespace_not_fresh")
 inert=load(read_pin(SOURCE,SOURCE_SHA),SOURCE,"_root_r32_r2_enclosing_inert")
 need(inert.ROOT_ENABLED is False and inert.ROOT_REVIEWED_ACTIVATION is False and inert.ROOT_DRIVER_REVIEW_READY is False and inert.ROOT_DRIVER_SHA256 is None,"source_defaults_changed")
 pins,software,aliases=inert._expected_pins()
 need(aliases==12 and len(pins)==INERT_PIN_COUNT and len(software)==5,"public_closure_shape")
 pins.update({str(SOURCE):SOURCE_SHA,str(ACTIVE_SOURCE):SOURCE_SHA,str(TEST):TEST_SHA,str(CU):CU_SHA,str(IMAGE):IMAGE_SHA,str(Path(__file__)):_ROOT_SELF_SHA256})
 pins.update({str(PACKET/n):h for n,h in PACKET_PINS.items()})
 pins.update({str(REVIEW/n):h for n,h in ROOT_REVIEW_PINS.items()})
 pins[str(REVIEW/"README.md")]=ROOT_REVIEW_README_SHA

 for path,digest in PROFILER_CACHE_PINS.items():pins[str(Path(path))]=digest
 pins[str(PROFILER_PROOF)]=PROFILER_PROOF_SHA
 pins[str(PROFILER_RECORD)]=PROFILER_RECORD_SHA
 cu=load(read_pin(CU,CU_SHA),CU,"_root_r32_r2_enclosing_custody")
 scope=cu.held_public_sources(pins,software)
 retained={"scope":scope,"cu":cu,"inert":inert};_KEEPALIVE.append(retained)
 private,cli,raw_held=scope.__enter__();held=_canonical_held(raw_held);retained.update(private=private,cli=cli,raw_held=raw_held,held=held)

 image=load(_held_bytes(held,IMAGE),IMAGE,"_root_r32_r2_image")
 image.current_image_check(private)
 need(sys.version_info[:3]==(3,11,5),"fixed_profiler_compiler")
 proof=load(_held_bytes(held,PROFILER_PROOF),PROFILER_PROOF,"_root_r32_r2_held_profiler_proof")
 record=json.loads(_held_bytes(held,PROFILER_RECORD))
 need(record.get("schema")=="iteration41.optional16.r29.profiler-bytecode-source-proof.v1" and record.get("status")=="READONLY_SOURCE_EQUIVALENCE_VERIFIED" and len(record.get("modules",[]))==3,"profiler_record_shape")
 expected_rows={r["module"]:r for r in record["modules"]}
 need(set(expected_rows)==set(proof.SOURCES),"profiler_module_set")
 for name,(source_path,digest) in proof.SOURCES.items():
  cache_path=Path(proof.importlib.util.cache_from_source(str(source_path)))
  row=proof.verify_module_cache(name,_held_bytes(held,source_path),_held_bytes(held,cache_path))
  need(row==expected_rows[name] and row["cache_sha256"]==PROFILER_CACHE_PINS[str(cache_path).replace("\\","/")],"held_profiler_code_graph_changed")
 retained.update(proof=proof,profiler_record=record)
 need(_held_bytes(held,SOURCE)==_held_bytes(held,ACTIVE_SOURCE),"activated_source_copy_mismatch")
 active=load(_held_bytes(held,ACTIVE_SOURCE),ACTIVE_SOURCE,"_root_r32_r2_driver_held_active")
 need(active.ROOT_ENABLED is False and active.ROOT_REVIEWED_ACTIVATION is False and active.ROOT_DRIVER_REVIEW_READY is False and active.ROOT_DRIVER_SHA256 is None,"held_defaults_changed")
 active.ROOT_ENABLED=True;active.ROOT_REVIEWED_ACTIVATION=True;active.ROOT_DRIVER_SHA256=SOURCE_SHA
 active.DRIVER_TEST_SHA256=TEST_SHA;active.ROOT_DRIVER_REVIEW_READY=True
 active.ROOT_DRIVER_REVIEW_PINS=dict(ROOT_REVIEW_PINS);active.ROOT_DRIVER_PACKET_PINS=dict(PACKET_PINS)
 active._validate_candidate_review(held);active._validate_r32_candidate_review(held);active._validate_r28_lineage(held);active._validate_driver_review(held)
 inner_pins,inner_software,inner_aliases=active._expected_pins()
 need(inner_aliases==ACTIVE_ALIAS_COUNT and inner_software==software and len(inner_pins)==ACTIVE_PIN_COUNT and all(sha(_held_bytes(held,p))==h for p,h in inner_pins.items()),"inner_closure_not_externally_held")
 need(not active.CONTROL.exists() and not active.SCRATCH.exists(),"driver_namespace_not_fresh")
 if args==["--activation-precheck"]:
  scope.__exit__(None,None,None)
  print(json.dumps({"schema":"iteration41.optional16.r32.root-activation-precheck.v1","status":"HELD_READONLY_PRECHECK_PASSED","complete_held_source_and_software_count":len(held),"inner_held_source_and_software_count":len(inner_pins)+len(inner_software),"complete_custody_postverified":True,"profiler_cache_code_graph_matches_pinned_source":True,"fixed_activated_source_origin":True,"private_controls_created":False,"sdk_imported":False,"child_started":False,"strict_cases_passed":0,"case_pass":False,"g1_accepted":False},sort_keys=True));return 0
 control=private.create_private_directory(CONTROL);control.verify();retained.update(control=control,active=active)
 control.write_bytes("root-consumed.json",canonical({"schema":"iteration41.optional16.r32.root-enclosing-attempt.v1","driver_sha256":SOURCE_SHA,"strict_cases_passed":0,"status":"CONSUMED"}))
 OUT.mkdir()
 sink=BoundedSink();stderr=BoundedSink();saved_stdout=sys.stdout;saved_stderr=sys.stderr
 sys.stdout=sink;sys.stderr=stderr;application=None;started=time.monotonic();complete=False
 try:
  application=_run_active_application(active)
  done=application["done"];state=application["state"];thread=application["thread"]
  started=application["started"];complete=application["complete"]
  retained.update(sink=sink,stderr=stderr,done=done,state=state,thread=thread,application=application)
 finally:
  if complete and application is not None and not application["thread"].is_alive():sys.stdout=saved_stdout;sys.stderr=saved_stderr
 safe_base={"schema":"iteration41.optional16.r32.root-held-observation.v1","orders":"UNOBSERVED","cancels":"UNOBSERVED","strict_cases_passed":0,"case_pass":False,"optional16_real_accepted":0,"g1_accepted":False,"whole_command_hard_deadline":False,"profiler_source_and_cache_held":True,"profiler_cache_code_graph_matches_pinned_source":True,"child_cache_origin_observed":False,"held_path_keys_normalized":True,"normalization_no_ambient_resolution":True}
 if not complete or application is None or application["thread"].is_alive() or application["state"]["error"] is not None or sink.overflow or stderr.overflow or stderr.getvalue()!="":
  result={**safe_base,"status":"ROOT_APPLICATION_UNCERTAIN","complete_custody_retained_until_root_process_exit":True,"complete_custody_postverified":False,"late_frame_parsed":False}
  save_new(OUT/"root-observation.json",result);print(json.dumps(result,sort_keys=True),file=saved_stdout);return 2
 need(not active._KEEPALIVES,"inner_native_or_source_state_retained")
 raw=sink.getvalue().encode("ascii","strict")
 need(0<len(raw)<=MAX_PARENT_FRAME_BYTES and raw.count(b"\n")==1 and raw.endswith(b"\n"),"parent_frame_shape")
 report=json.loads(raw)
 need(type(state["code"]) is int and state["code"] in (0,2),"parent_exit_code_type")
 need(type(report) is dict and type(report.get("strict_cases_passed")) is int and report["strict_cases_passed"]==0 and report.get("case_pass") is False and report.get("registry_admission") is False and report.get("acceptance")=="NOT_ACCEPTED_OPTIONAL16","parent_projection_contract")
 need(report.get("schema")=="iteration41.optional16.r32.root-matrix-projection.v3" and report.get("status") in {"BLOCKED","LOCAL_DIAGNOSTIC_ONLY"},"parent_projection_schema")
 need(state["code"]==(0 if report["status"]=="LOCAL_DIAGNOSTIC_ONLY" else 2),"parent_status_exit_pair")
 need(report.get("provider_session_created") is False and report.get("network_access_allowed") is False,"matrix_no_provider_contract")
 need(report.get("cleanup") in {"CLEAN","NOT_STARTED"},"matrix_resource_cleanup_unverified")
 if report["status"]=="LOCAL_DIAGNOSTIC_ONLY":
  ids=[prefix+"-E"+str(e)+"-R"+str(r)+"-M"+str(m) for prefix in ("D","GZ") for e in (0,1) for r in (0,1) for m in (0,1)]
  need(type(report.get("completed_case_count")) is int and report["completed_case_count"]==16 and type(report.get("case_ids")) is list and report["case_ids"]==ids,"matrix_case_coverage")
  need(report.get("cleanup")=="CLEAN" and report.get("raw_capture_saved") is True and report.get("reason") is None,"matrix_completion_state")
 control.verify()
 try:scope.__exit__(None,None,None)
 except BaseException:
  result={**safe_base,"status":"ROOT_OUTER_POSTVERIFY_FAILED","complete_custody_postverified":False,"complete_custody_retained_until_root_process_exit":False,"python_references_retained":True,"native_cleanup_completed_before_outer_release":True}
  save_new(OUT/"root-observation.json",result);print(json.dumps(result,sort_keys=True));return 2
 result={**safe_base,"status":"ROOT_ACTUAL_OBSERVED_PENDING_REVIEW","root_exit_code":state["code"],"complete_held_source_and_software_count":len(held),"inner_held_source_and_software_count":len(inner_pins)+len(inner_software),"complete_custody_postverified":True,"complete_custody_retained_until_root_process_exit":False,"root_application_elapsed_seconds":round(time.monotonic()-started,3),"root_observation":report}
 save_new(OUT/"root-observation.json",result);print(json.dumps(result,sort_keys=True));return state["code"]

if __name__=="__main__":
 try:code=main()
 except BaseException as exc:
  print(json.dumps({"status":"ROOT_R32_R1_BLOCKED","error_type":type(exc).__name__,"references_retained_until_root_process_exit":bool(_KEEPALIVE),"orders":"UNOBSERVED","cancels":"UNOBSERVED","strict_cases_passed":0},sort_keys=True));code=2
 raise SystemExit(code)
