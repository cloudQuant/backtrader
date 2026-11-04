import copy, importlib.util, sys
from pathlib import Path
repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader')
spec=importlib.util.spec_from_file_location('sample_helpers',repo/'tests/unit/test_iter61_example_modes.py')
h=importlib.util.module_from_spec(spec); sys.modules[spec.name]=h; spec.loader.exec_module(h)
key,mode,engine=sys.argv[1:4]; directory=Path('/tmp/iter61-daily027.bZoa32/input'); runner=h.load_runner(key)
sys.path.insert(0,str(h.RUNNERS[key].parent)); config=h.config_for(runner,directory); runner._load_config=lambda: copy.deepcopy(config)
out=Path('/tmp/iter61-eval025026.I5g1dG')/f'{key}-{mode}-{engine}'
args=['--output-dir',str(out),'--data-dir',str(directory),'--asset-batch-size','0','--no-charts','--factor-mode',mode]
if engine=='next': args.append('--runnext')
code=runner.main(args); print('RUNNER_EXIT',code,flush=True); raise SystemExit(code)
