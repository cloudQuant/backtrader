import hashlib
import json
import pathlib
import subprocess
import sys

root = pathlib.Path("D:/temp/i71_sma_pair_opt")
worker = root / "bench_serial_r4_worker.py"
assert len(sys.argv) == 3, "usage: driver PYTHON OUTPUT_NEW_FILE"
exe, output = sys.argv[1:]
pins = {"baseline": "c7e8fa855a97a5befb5ae20871f1a2ac90c97ebfa38e9f9e1a87284a18f2b487",
        "candidate": "d8db3df6a348b89514f1611481668a0606f1403687a0d61bd233459eb355b830"}
worker_sha = hashlib.sha256(worker.read_bytes()).hexdigest()
rows = []
for count in (1, 8):
    for pair in range(4):
        order = ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
        for variant in order:
            result = subprocess.run([exe, "-B", str(worker), str(root / variant), str(count)],
                                    cwd=str(root / variant), check=True, capture_output=True, text=True)
            row = json.loads(result.stdout)
            assert row["source_sha256"] == pins[variant]
            row.update(variant=variant, pair=pair)
            rows.append(row)
        assert rows[-1]["output_sha256"] == rows[-2]["output_sha256"]
assert hashlib.sha256(worker.read_bytes()).hexdigest() == worker_sha
with open(output, "x", encoding="utf-8", newline="\n") as file:
    json.dump({"worker_sha256": worker_sha, "rows": rows}, file, indent=2)
    file.write("\n")
print(output)
