from pathlib import Path
import json
from backtrader.stores.btapistore import BtApiStore

class FakeCtpSdk:
    def __init__(self): self.write_calls=[]
    def build_ctp_execution_approval_context(self, **kwargs): return kwargs
    def redeem_ctp_execution_approval(self, *args, **kwargs): return None
    def confirm_ctp_settlement_from_approval(self, *args, **kwargs): return None
    def reserve_ctp_execution_budget(self, *args, **kwargs): return None
    def submit_order(self, *args, **kwargs): self.write_calls.append('submit_order')

api=FakeCtpSdk()
managed=BtApiStore(provider='btapi', api=api, exchange_kwargs={'CTP___FUTURE': {}})
view=managed.sdk_api
assert view is not None and view is not api
ordinary_hidden={}
for name in ('_api','_invoke','__dict__','_CtpSdkAuthorityView__api','submit_order'):
    try: getattr(view,name)
    except AttributeError: ordinary_hidden[name]=True
    else: ordinary_hidden[name]=False
raw=object.__getattribute__(view,'_CtpSdkAuthorityView__api')
slot_descriptor=type(view).__dict__['_CtpSdkAuthorityView__api']
raw_via_slot=slot_descriptor.__get__(view,type(view))
partial=view.reserve_ctp_execution_budget
raw_via_partial=object.__getattribute__(partial.args[0],'_CtpSdkAuthorityView__api')
assert raw is api and raw_via_slot is api and raw_via_partial is api
raw.submit_order(order='synthetic-only')
assert api.write_calls == ['submit_order']
# The example's private fallback is exercisable with an unmanaged CTP fake factory;
# no SDK import is needed because the unmanaged branch honors the injected api_cls.
unmanaged=BtApiStore(provider='ctp', api_cls=lambda **_kwargs: api)
assert unmanaged.sdk_api is None and unmanaged._api is None
fallback_raw=unmanaged._ensure_api_ready()
assert fallback_raw is api and unmanaged.sdk_api is None
result={
    'ordinary_attribute_guards': ordinary_hidden,
    'object_getattribute_returns_raw': raw is api,
    'slot_descriptor_returns_raw': raw_via_slot is api,
    'partial_self_reaches_raw': raw_via_partial is api,
    'fake_raw_write_counter_after_introspection': api.write_calls,
    'unmanaged_ctp_prestart_sdk_api_is_none': True,
    'unmanaged_ctp_private_fallback_returns_raw_client': fallback_raw is api,
    'sdk_import_guard': 'bt_api_py, bt_api_ctp and _ctp imports blocked; no hit in final probe',
    'provider_or_network': False,
}
Path(r'D:\temp\iteration41-store-sdk-api-guard-only-20260927\independent-qa-r0\introspection-probe.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
