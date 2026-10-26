"""Root-only bounded reader; export only configured indices and finite categories."""
import hashlib
import json
import logging
from pathlib import Path
import sys

EXAMPLE = Path('D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute')
PREFIX = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1/consumer').resolve()
OUT = Path('D:/temp/i51-root-nojoin-profile-metadata-20261027-r1.json')
HELPER_PIN = 'c4269bb9b78e40fd60843e32af5616dece5052d621258add12ba82f9696c1982'
ALLOWED = frozenset(('set1_group1','set1_group1_vpn','set1_group2','set1_group2_vpn','set1_group3_vpn','set2_7x24','set2_7x24_4000x','set2_7x24_vpn'))

def main():
    assert not OUT.exists() and sys.flags.isolated and Path(sys.prefix).resolve() == PREFIX
    assert hashlib.sha256((EXAMPLE/'protected_simnow.py').read_bytes()).hexdigest() == HELPER_PIN
    logging.disable(logging.CRITICAL)
    sys.path.insert(0,str(EXAMPLE))
    phase = 'public_artifact_gate'
    result = {'schema':1,'provider_invoked':False,'native_api_created':False,'credential_exported':False,'helper_sha256':HELPER_PIN}
    try:
        import protected_simnow as bridge
        from bt_api_ctp.ctp_env_selector import official_simnow_profile_for_td_front, verify_official_simnow_profile
        with bridge.trusted_installed_capability_import_context(('bt_api_base','bt_api_ctp')):
            bridge._verify_pinned_sdk_distributions(('bt_api_base','bt_api_ctp'),pins=bridge._SDK_PINS)
        phase = 'registered_bounded_load'
        registration, registry = bridge._registered_runtime()
        config = bridge.load_runtime_config(registration.runtime_dir,registry=registry)
        phase = 'effective_seal'
        effective = bridge.resolve_runtime_config(config,registry)
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        phase = 'sealed_pair_categories'
        _, _, pairs = binding._sealed_private_config(effective,registry)
        rows = []
        for index,pair in enumerate(pairs):
            category = official_simnow_profile_for_td_front(pair.td_front)
            verified = category in ALLOWED and verify_official_simnow_profile(pair.td_front,pair.md_front,category) is True
            rows.append({'configured_index':index,'category':category if verified else 'UNVERIFIED_PAIR','official_pair_verified':verified})
        result.update(status='PASS_ROOT_BOUNDED_PROFILE_METADATA_ONLY',pair_count=len(pairs),profiles=rows)
        assert hashlib.sha256((EXAMPLE/'protected_simnow.py').read_bytes()).hexdigest() == HELPER_PIN
    except BaseException:
        result.update(status='BLOCKED_ROOT_BOUNDED_PROFILE_METADATA',phase=phase)
    with OUT.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps(result))
    return 0 if result['status'].startswith('PASS') else 2

if __name__ == '__main__':
    sys.exit(main())
