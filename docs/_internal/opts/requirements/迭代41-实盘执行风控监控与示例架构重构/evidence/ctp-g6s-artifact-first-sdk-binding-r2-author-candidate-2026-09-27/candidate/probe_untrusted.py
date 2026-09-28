from pathlib import Path
from backtrader_runtime.ctp_windows_artifact_custody import WindowsArtifactCustody
try:
 c=WindowsArtifactCustody.acquire('D:/temp/iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1',('README.md',),expected_sha256={'README.md':'0'*64})
except Exception as e:
 print(type(e).__name__,getattr(e,'reason',type(e).__name__))
