"""Source probes must not mutate a checkout shared with other work."""

import ast
from pathlib import Path

from scripts import iter28_fingerprint_probe as probe
from scripts.ci.classify_pr_risk import classify_risk


def test_fingerprint_probe_mutates_only_snapshot_and_rejects_missing_files(tmp_path, monkeypatch):
    module = probe.load_module()
    snapshot = probe.snapshot_inputs(module, tmp_path)
    original_write = Path.write_bytes
    original_unlink = Path.unlink

    def only_temporary_write(path, value):
        assert tmp_path.resolve() in path.resolve().parents, path
        return original_write(path, value)

    def only_temporary_unlink(path, *args, **kwargs):
        assert tmp_path.resolve() in path.resolve().parents, path
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", only_temporary_write)
    monkeypatch.setattr(Path, "unlink", only_temporary_unlink)
    result = probe.probe_snapshot(module, snapshot)
    assert result["all_pass"] and result["restored_equal"]
    assert set(result["per_file"]) == set(probe.SPLIT_FILES)
    assert len(result["per_file"]) == 10
    assert all(row["missing_file_rejected"] for row in result["per_file"].values())


def test_split_files_retain_core_risk_ownership_and_independent_manifest_coverage():
    for path in [*probe.SPLIT_FILES, "backtrader/_cerebro/future_loop.py"]:
        assert classify_risk([path]) == "R2"
    ownership = (probe.REPO / ".github/CODEOWNERS").read_text(encoding="utf-8")
    matches = [line.split() for line in ownership.splitlines() if line.startswith("/backtrader/")]
    facade_owner = next(parts[1:] for parts in matches if parts[0] == "/backtrader/cerebro.py")
    mixin_owner = next(parts[1:] for parts in matches if parts[0] == "/backtrader/_cerebro/")
    assert mixin_owner == facade_owner
    for script in (
        "run_iter27_hf_t1_independent_acceptance.py",
        "run_iter27_fq3_independent_acceptance.py",
    ):
        tree = ast.parse((probe.REPO / "scripts" / script).read_text(encoding="utf-8"))
        paths = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Path"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        assert set(probe.SPLIT_FILES) <= paths, script
