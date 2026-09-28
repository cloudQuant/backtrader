import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(r"D:\temp\ac41-63-zero-write-independent-qa-packet-20260927")
archive = root / "independent-qa.raw.zip"
include_roots = [root / "frozen-input", root / "isolated-source", root / "independent-run", root / "REPORT.md"]
with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as zf:
    for item in include_roots:
        paths = [item] if item.is_file() else sorted(p for p in item.rglob("*") if p.is_file())
        for path in paths:
            zf.write(path, path.relative_to(root).as_posix())

files = []
for base in include_roots:
    paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": digest})
zip_bytes = archive.read_bytes()
manifest = {
    "schema": "ac41-63-zero-write-independent-qa-packet.v1",
    "verdict": "NOT_AC41_63_PASS",
    "frozen_author_manifest_sha256": "f025ca7ca0c0cfa927ff3d7694d581c85ceb1bece56d6ce7abef9242c94e3c7d",
    "frozen_author_zip_sha256": "6ece5cc5f574248f7c488e164b9018a5bed316ff3dbdfdcee25ade10cabdf267",
    "raw_zip": {"path": archive.name, "size": len(zip_bytes), "sha256": hashlib.sha256(zip_bytes).hexdigest()},
    "file_count": len(files),
    "files": files,
}
(root / "packet-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"file_count": len(files), "zip_size": len(zip_bytes), "zip_sha256": manifest["raw_zip"]["sha256"], "manifest_sha256": hashlib.sha256((root / "packet-manifest.json").read_bytes()).hexdigest()}, sort_keys=True))
