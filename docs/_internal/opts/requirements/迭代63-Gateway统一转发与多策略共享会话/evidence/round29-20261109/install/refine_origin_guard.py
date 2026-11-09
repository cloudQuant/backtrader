from pathlib import Path
import shutil
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4');p=T/'bootstrap/origin_guard.py';shutil.copyfile(p,T/'origin_guard-v1.py');s=p.read_text()
old="        if spec is None: raise ModuleNotFoundError('target module unavailable: ' + fullname, name=fullname)"
new="""        if spec is None:
            if fullname in {'bt_api_py.forwarding', 'bt_api_py.gateway', 'bt_api_py._gateway_wire', 'bt_api_py.runtime_plugins.gateway_dispatch'}:
                write('absent-retired-module', {'module': fullname})
                return None
            raise ModuleNotFoundError('target module unavailable: ' + fullname, name=fullname)"""
assert s.count(old)==1;p.write_text(s.replace(old,new))
p=T/'launch_v2.py';s=p.read_text().replace("('preflight','sdk-installed','sdk-installed-v2','verify','verify-final')","('preflight','preflight-v2','sdk-installed','sdk-installed-v2','verify','verify-final')").replace("'preflight':'guard_preflight.py'","'preflight':'guard_preflight.py','preflight-v2':'guard_preflight.py'")
(T/'launch_v3.py').write_text(s)
