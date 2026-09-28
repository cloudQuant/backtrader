"""Validate the archived candidate and write its relative hash index."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest() -> None:
    frozen = json.loads((ROOT / "FROZEN-MANIFEST.json").read_text(encoding="utf-8"))
    source_manifest = ROOT / "SOURCE-MANIFEST.json"
    if sha256(source_manifest) != frozen["frozen_source"]["manifest_sha256"]:
        raise SystemExit("copied V21 source manifest hash mismatch")
    for artifact in frozen["artifacts"].values():
        path = ROOT / artifact["path"]
        if not path.is_file() or sha256(path) != artifact["sha256"]:
            raise SystemExit(f"candidate artifact hash mismatch: {artifact['path']}")


def verify_markdown_links() -> int:
    pattern = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
    links_checked = 0
    for document in ROOT.glob("*.md"):
        for target in pattern.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("https://", "http://", "mailto:")):
                continue
            local_target = target.split("#", maxsplit=1)[0]
            if local_target and not (document.parent / local_target).is_file():
                raise SystemExit(f"broken local link in {document.name}: {target}")
            links_checked += 1
    return links_checked


def main() -> None:
    verify_manifest()
    links_checked = verify_markdown_links()
    index_path = ROOT / "hash-index.json"
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and path != index_path and "__pycache__" not in path.parts
    ]
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())
    ]
    index = {
        "schema": "iteration41-evidence-hash-index.v1",
        "archive": ROOT.name,
        "self_hash_excluded": True,
        "links_checked": links_checked,
        "files": entries,
    }
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"files_indexed": len(entries), "links_checked": links_checked}, indent=2))


if __name__ == "__main__":
    main()
