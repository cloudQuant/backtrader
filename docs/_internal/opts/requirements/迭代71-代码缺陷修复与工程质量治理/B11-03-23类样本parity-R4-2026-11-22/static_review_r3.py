"""Conservative static prefilter for the explicit R3 pilot; not a safety proof."""

import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "snapshot"
MATRIX = Path("D:/temp/i71_b1103_matrix_c5fc/matrix.json")
selected = (
    "CandleStopColor",
    "CCIWoodiesIndicator",
    "CGOscillator",
    "ClosePriceFractals",
    "ColorHMA",
    "ColorMetroWprIndicator",
    "ColorX2MA",
    "DarvasBoxesSystem",
    "DotsIndicator",
    "EFDistanceIndicator",
    "EmaRsiVa",
    "EnvelopesJpAlonso",
    "F2aAOIndicator",
    "FatlFilter",
    "FineTuningMA",
    "FisherOrgV1",
    "FisherOrgV1Sign",
    "ForceDiverSign",
    "ForceIndexEMA",
    "ForceIndexEma",
    "ForecastOscilator",
    "FractalAMAMBK",
    "FRASMAv2Indicator",
)
available = {
    "Indicator",
    "SMA",
    "SimpleMovingAverage",
    "EMA",
    "ExponentialMovingAverage",
    "SmoothedMovingAverage",
    "Highest",
    "Lowest",
    "StandardDeviation",
    "ATR",
    "AverageTrueRange",
    "BollingerBands",
    "CrossOver",
    "AverageDirectionalMovementIndex",
    "MinusDirectionalIndicator",
    "PlusDirectionalIndicator",
    "RSI",
    "RelativeStrengthIndex",
    "OBV",
    "MovingAverage",
    "MovingAverageBase",
    "MovAv",
}
matrix_bytes = MATRIX.read_bytes()
matrix_sha = hashlib.sha256(matrix_bytes).hexdigest()
assert matrix_sha == "715784c4666c55686f57284dfeb127734b2808f32deed0d1d2b24f0c08e0096e"
rows = json.loads(matrix_bytes)["rows"]
out = []
for name in selected:
    matches = [row for row in rows if row["class"] == name]
    assert len(matches) == 1
    row = matches[0]
    raw = (ROOT / row["source"]).read_bytes()
    tree = ast.parse(raw)
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )
    init = next(
        (
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ),
        None,
    )
    assert init is None or (
        len(init.args.args) <= 1
        and not init.args.vararg
        and not init.args.kwarg
        and not init.args.kwonlyargs
    )
    assert not row["historical_design"] and not row["historical_runtime"]
    imports = sorted(
        {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
    )
    assert set(imports) <= {
        "",
        "math",
        "collections",
        "backtrader.functions",
        "linebuffer",
    }
    exposed = sorted(
        {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 2
            and node.module is None
            for alias in node.names
        }
    )
    assert set(exposed) <= available
    assert not any(
        isinstance(node, (ast.For, ast.While, ast.With, ast.Try))
        or isinstance(node, ast.Expr)
        and not isinstance(node.value, ast.Constant)
        or isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.decorator_list
        for node in tree.body
    )
    prohibited = {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "system",
        "popen",
        "connect",
        "urlopen",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
    }
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert not calls & prohibited, (name, calls & prohibited)
    text = ast.get_source_segment(raw.decode("utf8"), cls) or ""
    assert "data1" not in text and "datas[1]" not in text
    out.append(
        {
            "class": name,
            "module": row["module"],
            "source": row["source"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "imports": imports,
            "indicator_exports": exposed,
            "construction": "one-feed/default assumed, runtime verified separately",
        }
    )
print(
    json.dumps(
        {
            "scope": "syntax filter only; not complete import-safety or formula proof",
            "matrix_sha256": matrix_sha,
            "rows": out,
        },
        indent=2,
    )
)
