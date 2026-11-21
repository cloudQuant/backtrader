"""Check benchmark digests against formulas independent of Backtrader."""
import hashlib
import json
import math
from pathlib import Path
import struct

root = Path(__file__).parent
result = json.loads((root / 'result_r2.json').read_text(encoding='utf-8'))
n = result['N']
close = [100 + 0.003 * i + 3 * math.sin(i * .07) for i in range(n)]

def digest(values):
    h = hashlib.sha256()
    for value in values:
        h.update(struct.pack('!d', value))
    return h.hexdigest()

expected = {
    'ordinary': digest((value * (1.01 + i * .001) + (value + .6)) / 2.0
                       for value in close for i in range(16)),
    'factor': digest((value * 1.01 + value * 1.02) / 2.0 for value in close),
}
for item in result['summary']:
    if item['sha256'] != expected[item['scenario']]:
        raise AssertionError((item['scenario'], item['runonce'], item['sha256'], expected))
print(json.dumps(expected,indent=2))
