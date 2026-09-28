from __future__ import annotations
import hashlib,json,pathlib,zipfile
ROOT=pathlib.Path(r"D:\temp\ac41-63-writer-slice3-r2-independent-qa-20260927")
CONTENT=ROOT/"qa-package/content"; MANIFEST=CONTENT/"QA-PACKAGE-MANIFEST.json"; ARCHIVE=ROOT/"qa-package/QA-PACKAGE.zip"
def sha(b): return hashlib.sha256(b).hexdigest()
rows=[]
for p in sorted(CONTENT.rglob("*")):
    if p.is_file() and p!=MANIFEST:
        b=p.read_bytes(); rows.append({"path":p.relative_to(CONTENT).as_posix(),"bytes":len(b),"sha256":sha(b)})
meta={"schema":"ac41-63-writer-slice3-independent-qa-v1","verdict":"PASS_STATIC_AUDIT_SCOPE_ONLY; NO_WRITE / LIVE_NO_GO retained","author_input_zip_sha256":"4d90d2e1abda09c44dfeb4845526b7a07b12d617bab9952de60d360832b37000","artifact_count":len(rows),"artifacts":rows}
MANIFEST.write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
with zipfile.ZipFile(ARCHIVE,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(CONTENT.rglob("*")):
        if p.is_file():z.write(p,p.relative_to(CONTENT).as_posix())
with zipfile.ZipFile(ARCHIVE) as z:
    assert z.testzip() is None and len(z.namelist())==len(rows)+1
    for row in rows:
        data=z.read(row["path"]);assert len(data)==row["bytes"] and sha(data)==row["sha256"],row["path"]
    assert z.read("QA-PACKAGE-MANIFEST.json")==MANIFEST.read_bytes()
h=sha(ARCHIVE.read_bytes());(ARCHIVE.parent/"QA-PACKAGE.SHA256.txt").write_text(f"{h}  QA-PACKAGE.zip\n",encoding="ascii")
print(json.dumps({"zip":str(ARCHIVE),"zip_sha256":h,"manifest_sha256":sha(MANIFEST.read_bytes()),"receipt_sha256":sha((CONTENT/"QA-RECEIPT.md").read_bytes()),"member_count":len(rows)+1,"artifact_count":len(rows),"crc":"clean"},sort_keys=True))
