"""Collect offline source-baseline evidence for Iteration 41 AI producers.

The three AI products intentionally remain independent repositories.  This
collector records the exact local Git identity and the digest of their
portable review-evidence implementation without importing any producer,
Backtrader, SDK, provider, or MCP capability.  It is evidence for a review
boundary only: it never grants deployment, execution, control, or credential
authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple


SCHEMA_VERSION = "iteration41.ai-producer-source-inventory.v1"
PRODUCT_SPECS = (
    ("backtrader-agent", "backtrader_agent"),
    ("backtrader-skills", "backtrader_skills"),
    ("backtrader-mcp", "backtrader_mcp"),
)
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_PYPROJECT_VERSION = re.compile(r'^\s*version\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)


class ProducerInventoryError(ValueError):
    """A deterministic, non-secret collector rejection."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_file(root: Path, relative_path: str) -> Path:
    """Return one in-root regular file without following a leaf link."""

    candidate = root / relative_path
    try:
        lexical = candidate.absolute()
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        lexical.relative_to(root.absolute())
        resolved.relative_to(resolved_root)
        leaf = os.lstat(str(candidate))
    except (OSError, ValueError):
        raise ProducerInventoryError("required producer file is unavailable") from None
    if stat.S_ISLNK(leaf.st_mode) or not stat.S_ISREG(leaf.st_mode):
        raise ProducerInventoryError("required producer file must be a regular non-link file")
    return resolved


def _read_regular_file(root: Path, relative_path: str) -> bytes:
    path = _regular_file(root, relative_path)
    try:
        return path.read_bytes()
    except OSError:
        raise ProducerInventoryError("required producer file cannot be read") from None


def _git_output(root: Path, *arguments: str) -> bytes:
    """Run Git without a shell and return only its raw stdout bytes."""

    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise ProducerInventoryError("git is unavailable for producer baseline collection") from None
    if completed.returncode != 0:
        raise ProducerInventoryError("producer source root is not a readable Git checkout")
    return completed.stdout


def _verified_git_root(root: Path) -> Path:
    try:
        lexical = root.absolute()
        result = os.lstat(str(root))
        if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
            raise ProducerInventoryError("producer source root must be a non-link directory")
        resolved = root.resolve(strict=True)
    except OSError:
        raise ProducerInventoryError("producer source root is unavailable") from None
    git_root = _git_output(resolved, "rev-parse", "--show-toplevel").decode("utf-8", "strict").strip()
    try:
        if Path(git_root).resolve(strict=True) != resolved:
            raise ProducerInventoryError("producer source root must be the Git checkout root")
    except OSError:
        raise ProducerInventoryError("producer Git root cannot be resolved") from None
    # Keep this variable to make the lexical non-link inspection above explicit
    # to readers and static checkers; only the resolved directory is recorded.
    del lexical
    return resolved


def _package_version(pyproject: bytes, package_init: bytes) -> Optional[str]:
    """Extract a non-authoritative display version without importing a package."""

    try:
        pyproject_text = pyproject.decode("utf-8")
    except UnicodeDecodeError:
        raise ProducerInventoryError("producer pyproject must be UTF-8") from None
    match = _PYPROJECT_VERSION.search(pyproject_text)
    if match is not None:
        return match.group(1)
    try:
        tree = ast.parse(package_init.decode("utf-8"), filename="__init__.py")
    except (SyntaxError, UnicodeDecodeError):
        raise ProducerInventoryError("producer package initializer cannot be parsed") from None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _dirty_manifest_digest(root: Path) -> Tuple[bool, str]:
    """Hash tracked/untracked state without placing file names or contents in output."""

    status = _git_output(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    working = _git_output(root, "diff", "--binary", "--no-ext-diff")
    staged = _git_output(root, "diff", "--cached", "--binary", "--no-ext-diff")
    untracked = _git_output(root, "ls-files", "--others", "--exclude-standard", "-z")
    digest = hashlib.sha256()
    for label, content in (
        (b"status", status),
        (b"working", working),
        (b"staged", staged),
    ):
        digest.update(label)
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    for encoded_path in sorted(item for item in untracked.split(b"\0") if item):
        try:
            relative_path = encoded_path.decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise ProducerInventoryError("producer Git path is not UTF-8") from None
        content = _read_regular_file(root, relative_path)
        digest.update(b"untracked\0")
        digest.update(encoded_path)
        digest.update(b"\0")
        digest.update(_sha256_bytes(content).encode("ascii"))
        digest.update(b"\0")
    return bool(status), digest.hexdigest()


def _collect_product(product_name: str, package_name: str, root: Path) -> Dict[str, object]:
    verified_root = _verified_git_root(root)
    commit = _git_output(verified_root, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    if not _GIT_COMMIT.fullmatch(commit):
        raise ProducerInventoryError("producer Git commit has an unsupported format")
    pyproject = _read_regular_file(verified_root, "pyproject.toml")
    package_prefix = "src/{0}".format(package_name)
    package_init = _read_regular_file(verified_root, package_prefix + "/__init__.py")
    evidence_source = _read_regular_file(
        verified_root, package_prefix + "/deployment_evidence.py"
    )
    is_dirty, dirty_digest = _dirty_manifest_digest(verified_root)
    return {
        "product": product_name,
        "source_root": verified_root.as_posix(),
        "git_commit": commit,
        "working_tree_dirty": is_dirty,
        "working_tree_manifest_sha256": dirty_digest,
        "package_name": package_name,
        "package_version": _package_version(pyproject, package_init),
        "pyproject_sha256": _sha256_bytes(pyproject),
        "package_init_sha256": _sha256_bytes(package_init),
        "deployment_evidence_path": (package_prefix + "/deployment_evidence.py"),
        "deployment_evidence_sha256": _sha256_bytes(evidence_source),
    }


def collect_producer_inventory(
    roots: Iterable[Tuple[str, Path]],
) -> Dict[str, object]:
    """Collect reviewed source identity facts without importing producer code."""

    products = []
    seen_names = set()
    for product_name, root in roots:
        package_name = dict(PRODUCT_SPECS).get(product_name)
        if package_name is None or product_name in seen_names:
            raise ProducerInventoryError("producer product identity is not supported")
        seen_names.add(product_name)
        products.append(_collect_product(product_name, package_name, Path(root)))
    expected = {name for name, _ in PRODUCT_SPECS}
    if seen_names != expected:
        raise ProducerInventoryError("all three reviewed AI producer roots are required")
    products.sort(key=lambda item: str(item["product"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "SOURCE_BASELINE_ONLY",
        "products": products,
        "limitations": [
            "This artifact records local source identity only; it does not prove a built wheel, package installation, or runtime import origin.",
            "This artifact is review evidence only and never grants deployment, execution, control, provider, account, or credential authority.",
            "A changed Git working tree requires a newly collected artifact and independent review before it can be relied upon.",
        ],
    }


def _write_json_atomically(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".iteration41-ai-producers-", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="collect Iteration 41 AI producer source identities without importing producer code"
    )
    parser.add_argument("--agent-root", required=True, type=Path)
    parser.add_argument("--skills-root", required=True, type=Path)
    parser.add_argument("--mcp-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    roots = (
        ("backtrader-agent", args.agent_root),
        ("backtrader-skills", args.skills_root),
        ("backtrader-mcp", args.mcp_root),
    )
    try:
        payload = collect_producer_inventory(roots)
    except ProducerInventoryError as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error)}, ensure_ascii=False))
        return 2
    _write_json_atomically(args.output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "output": str(args.output),
                "products": [item["product"] for item in payload["products"]],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by a subprocess in CI.
    raise SystemExit(main())
