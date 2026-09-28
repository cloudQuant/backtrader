"""The reserved CTP private runtime must not put credentials in Git."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
PRIVATE_RUNTIME = ROOT / "examples" / "013_3_sa_midfreq_simnow" / "runtime-ctp-private"


def test_ctp_private_runtime_config_and_secrets_are_git_ignored_and_untracked() -> None:
    relative = PRIVATE_RUNTIME.relative_to(ROOT).as_posix()
    private_paths = tuple(
        "{0}/{1}".format(relative, name) for name in ("config.yaml", "secrets.yaml")
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--", *private_paths],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout.splitlines() == []

    for candidate in (
        private_paths[0],
        private_paths[1],
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", candidate],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 0, candidate
