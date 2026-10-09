"""Root-held public file custody for actual Iteration 41 validation."""
from contextlib import ExitStack,contextmanager
from pathlib import Path
import hashlib,sys,types
ROOT=Path('D:/source_code/backtrader')
PRIVATE='backtrader_runtime/certification_roundtrip_private.py'
PRIVATE_SHA='b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd'
CLI='backtrader_runtime/certification_binance_roundtrip_r3_cli.py'
CLI_SHA='62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76'

def check(value,code):
    if not value:raise RuntimeError(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def load(relative,pin,name):
    path=ROOT/relative
    raw=path.read_bytes()
    check(sha(raw)==pin,'root_helper_pin_mismatch')
    m=types.ModuleType(name);m.__file__=str(path);sys.modules[name]=m
    exec(compile(raw,str(path),'exec',dont_inherit=True),m.__dict__)
    return m

@contextmanager
def held_public_sources(pins,software_pins):
    private=load(PRIVATE,PRIVATE_SHA,'_root_public_custody_private')
    cli=load(CLI,CLI_SHA,'_root_public_custody_cli')
    api=private._api()
    all_pins={ROOT/p:h for p,h in pins.items()}
    all_pins.update({Path(p):h for p,h in software_pins.items()})
    identities={};raw_bytes={}
    with ExitStack() as stack:
        ancestors={p for path in all_pins for p in path.parents}
        for ancestor in sorted(ancestors,key=lambda p:(len(p.parts),str(p))):
            stack.enter_context(api.opened(ancestor,directory=True,access=0x80020080))
        for path,pin in all_pins.items():
            check(path.is_absolute(),'root_custody_path_invalid')
            handle,identity=stack.enter_context(cli._locked_readonly_file(path,private,api,allow_hardlinks=True))
            maximum=128*1024*1024 if path.suffix.lower()=='.dll' else 64*1024*1024
            raw=cli._read_bounded_handle(api,handle,maximum)
            check(sha(raw)==pin,'root_custody_pin_mismatch')
            identities[str(path)]=(handle,identity)
            raw_bytes[str(path)]=raw
        yield private,cli,raw_bytes
        for path,(handle,identity) in identities.items():
            check(cli._locked_file_identity(api,handle,private,allow_hardlinks=True)==identity,'root_custody_identity_changed')
            check(sha(Path(path).read_bytes())==all_pins[Path(path)],'root_custody_pin_changed')
