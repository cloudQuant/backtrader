"""Environment and packaged-capability diagnosis without candidate imports."""

import importlib.util
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import __version__
from .audit import IndependenceAuditor
from .canonical import hash_object


def _git_revision(start: Path) -> Tuple[Optional[str], Optional[str]]:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        marker = candidate / ".git"
        if marker.is_dir():
            git_dir = marker
        elif marker.is_file():
            text = marker.read_text(encoding="utf-8", errors="replace").strip()
            if not text.startswith("gitdir: "):
                continue
            git_dir = (candidate / text[8:]).resolve()
        else:
            continue
        head_path = git_dir / "HEAD"
        if not head_path.is_file():
            return None, None
        head = head_path.read_text(encoding="ascii", errors="replace").strip()
        if head.startswith("ref: "):
            reference = head[5:]
            ref_path = git_dir / reference
            commit = ref_path.read_text(encoding="ascii").strip() if ref_path.is_file() else None
            if commit is None:
                packed = git_dir / "packed-refs"
                if packed.is_file():
                    for line in packed.read_text(encoding="ascii", errors="replace").splitlines():
                        if line.endswith(f" {reference}"):
                            commit = line.split(" ", 1)[0]
                            break
            return reference.rsplit("/", 1)[-1], commit
        return None, head
    return None, None


def diagnose(product_root: Optional[Path] = None) -> Dict[str, Any]:
    default_product_root = Path(__file__).resolve().parents[2]
    product = Path(product_root).resolve() if product_root else default_product_root
    spec = importlib.util.find_spec("backtrader")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    branch, commit = _git_revision(origin.parent if origin else product)
    audit = IndependenceAuditor(product).audit() if (product / "src").is_dir() else None
    capabilities = {
        "offline_dataset_cas": True,
        "snapshot_catalog": True,
        "fourteen_scaffolds": True,
        "ast_security_validation": True,
        "hash_bound_approvals": True,
        "controlled_child_process": True,
        "session_hash_chain": True,
        "native_host_adapters": ["claude", "codex", "opencode", "openclaw"],
        "live_trading": False,
        "network_data": False,
        "os_sandbox": False,
        "verified_network_isolation": False,
    }
    environment = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "backtrader_import_path": str(origin) if origin else None,
        "backtrader_branch": branch,
        "backtrader_commit": commit,
    }
    return {
        "schema_version": "doctor-report-v1",
        "product": "backtrader-agent",
        "version": __version__,
        "status": (
            "ready" if origin and (audit is None or audit["status"] == "passed") else "blocked"
        ),
        "environment": environment,
        "environment_hash": hash_object(environment),
        "capabilities": capabilities,
        "independence_audit": audit,
        "limitations": [
            "P0 is offline and does not download market data.",
            "The controlled child process is not an OS sandbox.",
            "Network isolation is policy-based, not OS-verified.",
            "Fresh master/dev baseline orchestration requires separately registered engine roots.",
        ],
    }
