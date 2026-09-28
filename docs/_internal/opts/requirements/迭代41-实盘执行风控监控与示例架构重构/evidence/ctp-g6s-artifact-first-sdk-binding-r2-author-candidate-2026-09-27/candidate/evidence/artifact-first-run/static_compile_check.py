from pathlib import Path

paths = [
    Path("backtrader_runtime/ctp_sdk_artifact_binding.py"),
    Path("backtrader_runtime/ctp_simnow_td_trading_readiness.py"),
    Path("tests/unit/runtime/test_ctp_sdk_artifact_binding.py"),
    Path("tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py"),
]
for path in paths:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("compile() passed:", len(paths))
