from pathlib import Path
t=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl')
p=(t/'run_sdk.py').read_text().splitlines()
(t/'run_sdk_v2.py').write_text('\n'.join(p[:8])+"\nif __name__ == '__main__':\n"+'\n'.join('    '+line for line in p[8:])+'\n')
p=(t/'launch.py').read_text()
p=p.replace("('preflight','sdk-installed','verify')","('preflight','sdk-installed','sdk-installed-v2','verify','verify-final')").replace("'sdk-installed':'run_sdk.py','verify':'verify.py'","'sdk-installed':'run_sdk.py','sdk-installed-v2':'run_sdk_v2.py','verify':'verify.py','verify-final':'verify.py'")
(t/'launch_v2.py').write_text(p)
