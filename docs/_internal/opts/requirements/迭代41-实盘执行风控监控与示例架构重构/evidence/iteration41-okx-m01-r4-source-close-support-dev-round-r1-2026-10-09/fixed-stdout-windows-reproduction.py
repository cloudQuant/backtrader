"""Credential-free reproduction of fixed text versus binary stdout on this Windows host."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('D:/source_code/backtrader')
OUT = ROOT / '.codex-tmp/okx_m01_fixed_stdout_windows_reproduction_20261009.json'
EXPECTED = b'OKX_M01_ROOT_HELPER_GATE_R7_OK\n'
assert sys.platform == 'win32'
assert not OUT.exists()
commands = {
    'text': "import sys;sys.stdout.write('OKX_M01_ROOT_HELPER_GATE_R7_OK\\n')",
    'binary': "import sys;sys.stdout.buffer.write(b'OKX_M01_ROOT_HELPER_GATE_R7_OK\\n')",
}
facts = {}
for mode, source in commands.items():
    child = subprocess.run(['C:/anaconda3/python.exe', '-I', '-S', '-B', '-X', 'utf8', '-c', source],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    facts[mode] = {'exit_zero': child.returncode == 0, 'stderr_empty': child.stderr == b'',
        'stdout_bytes': len(child.stdout), 'matches_fixed_lf': child.stdout == EXPECTED,
        'matches_fixed_crlf': child.stdout == EXPECTED.replace(b'\n', b'\r\n')}
assert facts['text']['exit_zero'] and facts['text']['stderr_empty'] and facts['text']['matches_fixed_crlf']
assert facts['binary']['exit_zero'] and facts['binary']['stderr_empty'] and facts['binary']['matches_fixed_lf']
raw = Path(__file__).read_bytes()
receipt = {'status': 'FIXED_SYNTHETIC_STDOUT_TRANSLATION_REPRODUCED', 'facts': facts,
    'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
    'provider_account_operations': False, 'formal_m01_pass_count': 0,
    'original_gate_output_recovered': False}
OUT.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps(receipt))
