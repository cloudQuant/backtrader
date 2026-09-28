import sys
import backtrader_runtime.ctp_sdk_artifact_binding as binding
from backtrader_runtime.ctp_sdk_artifact_binding import CtpSdkArtifactBindingError
from backtrader_runtime.ctp_simnow_td_trading_readiness import require_trusted_ctp_sdk_artifact_before_client
assert binding._CODE_OWNED_ARTIFACT_POLICY is None
try:
    require_trusted_ctp_sdk_artifact_before_client()
except CtpSdkArtifactBindingError as exc:
    print('default_gate=', exc.reason)
else:
    raise AssertionError('default gate unexpectedly opened')
assert not any(name == 'bt_api_ctp' or name.startswith('bt_api_ctp.') for name in sys.modules)
print('sdk_package_imported=false')
