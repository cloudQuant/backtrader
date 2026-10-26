import base64
import csv
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import zipfile

PREFIX = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1/consumer').resolve()
OUT = Path('D:/temp/i51-nojoin-backtrader-20261027-r1/installed-verification.json')
WHEEL = Path('D:/temp/i51-nojoin-backtrader-20261027-r1/wheelhouse/back_trader_python-1.4.0-py3-none-any.whl')
EXAMPLE = Path('D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute')
assert Path(sys.prefix).resolve() == PREFIX and sys.flags.isolated
assert not OUT.exists()
def pin(path):
    raw = path.read_bytes()
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
assert pin(WHEEL)['sha256'] == 'dab4e74c4df206bae12649f45e0356e6df28be3f314d58a694444fb0e30b99cb'
dist = metadata.distribution('back-trader-python')
record = next(p for p in dist.files if str(p).endswith('.dist-info/RECORD'))
record_path = Path(dist.locate_file(record)).resolve()
checked = 0
with record_path.open(encoding='utf-8',newline='') as stream:
    for relative, encoded, size in csv.reader(stream):
        if encoded:
            p = Path(dist.locate_file(relative)).resolve()
            assert p.is_relative_to(PREFIX)
            raw = p.read_bytes()
            algo, expected = encoded.split('=',1)
            assert base64.urlsafe_b64encode(hashlib.new(algo,raw).digest()).rstrip(b'=').decode() == expected
            assert len(raw) == int(size)
            checked += 1
with zipfile.ZipFile(WHEEL) as z:
    names = [n for n in z.namelist() if n.startswith(('backtrader/','backtrader_runtime/')) and not n.endswith('/')]
    for name in names:
        assert Path(dist.locate_file(name)).read_bytes() == z.read(name)
import backtrader
import backtrader_runtime
import backtrader.stores.btapistore as store_module
for module in (backtrader, backtrader_runtime, store_module):
    assert Path(module.__file__).resolve().is_relative_to(PREFIX)
wrapper_class = store_module._create_ctp_wrapper_class()
wrapper = wrapper_class(ctp_join_observer=False)
assert wrapper.ctp_join_observer is False and wrapper.md_client is None and wrapper.trader_client is None
sys.path.insert(0,str(EXAMPLE))
import protected_simnow as bridge
with bridge.trusted_installed_capability_import_context(('bt_api_base','bt_api_ctp')):
    bridge._verify_pinned_sdk_distributions(('bt_api_base','bt_api_ctp'),pins=bridge._SDK_PINS)
result = {'status':'PASS_INSTALLED_WRAPPER_AND_PUBLIC_ARTIFACT_GATE_ONLY','wheel':pin(WHEEL),'record':pin(record_path),'record_hashed_entries_verified':checked,'payload_files_verified':len(names),'store_source':pin(Path(store_module.__file__)),'protected_helper':pin(EXAMPLE/'protected_simnow.py'),'explicit_nojoin_wrapper_created':True,'sdk_clients_created':False,'private_configuration_read':False,'native_api_created':False,'provider_called':False}
OUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
