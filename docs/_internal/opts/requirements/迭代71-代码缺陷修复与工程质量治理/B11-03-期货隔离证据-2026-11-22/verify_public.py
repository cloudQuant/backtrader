import hashlib, pathlib, subprocess
root=pathlib.Path(__file__).resolve().parent
cases=[
 ("D:/source_code/backtrader","f749673104e852784fb20e133933d0c3e20d9273",root/"bt",[
  "backtrader","tests/unit/feeds/test_futures_sessions.py","tests/unit/feeds/test_futures_selection_io.py",
  "tests/unit/feeds/test_futures_rollover_plan.py","tests/unit/feeds/test_futures_main_contract.py",
  "tests/unit/feeds/test_futures_expected_calendar.py","tests/unit/feeds/test_futures_calendar_evidence_roundtrip.py",
  "tests/unit/feeds/test_iter72_futures_type_and_export_fixes.py"]),
 ("D:/bt_api_py","53d3ebe621ef048c7f4c47f9125740c7fa29b3ee",root/"sdk",["bt_api_py"]),
 ("D:/bt_api_py/bt_api/bt_api_base","1bd1a13e36dbbf587acc63acdb5d8e0fdecaf6ca",root/"base",["src/bt_api_base"]),
]
def git_hash(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest().encode()
for repo, ref, target, paths in cases:
 raw=subprocess.check_output(["git","-C",repo,"ls-tree","-rz","--full-tree",ref,"--",*paths]);count=normalized=0
 for row in raw.split(b"\0"):
  if not row:continue
  meta,rawpath=row.split(b"\t",1);mode,kind,expected=meta.split(b" ")
  if mode not in (b"100644",b"100755") or kind!=b"blob":raise RuntimeError("non-regular source")
  p=target.joinpath(rawpath.decode("utf8"))
  if p.is_symlink() or not p.is_file():raise RuntimeError("missing or linked public source")
  b=p.read_bytes()
  if git_hash(b)!=expected:
   if git_hash(b.replace(b"\r\n",b"\n"))!=expected:raise RuntimeError("git mismatch "+rawpath.decode("utf8"))
   normalized+=1
  count+=1
 print(ref[:12],"verified_blobs",count,"crlf_normalized",normalized)
