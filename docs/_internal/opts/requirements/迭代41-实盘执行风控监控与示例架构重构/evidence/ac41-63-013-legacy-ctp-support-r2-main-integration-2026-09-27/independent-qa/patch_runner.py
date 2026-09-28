from pathlib import Path
path = Path(r'D:\temp\ac41-63-writer-partition4-candidate-r2-qa-20260927\safe_candidate_qa.py')
text = path.read_text(encoding='utf-8')
text = text.replace("    'broker_constructor_attempts': [],\n}", "    'broker_constructor_attempts': [],\n    'direct_no_fake_dotenv_imports': [],\n}")
anchor = '''BtApiStore.__init__ = deny_store_init
BtApiBroker.__init__ = deny_broker_init

# Replay the focused fake tests from the source tree copy.'''
insert = '''BtApiStore.__init__ = deny_store_init
BtApiBroker.__init__ = deny_broker_init

# First import each candidate with no fake dotenv module installed. The outer
# import/file guards make a reintroduced import-time dotenv call fail instead
# of silently falling back through a test stub.
if 'dotenv' in sys.modules:
    raise AssertionError('dotenv was already present before inert-import check')
for label, rel in (
    ('013_1_midfreq_cross_arbitrage', 'examples/013_1_midfreq_cross_arbitrage/ctp_example_support.py'),
    ('013_2_highfreq_calendar_arbitrage', 'examples/013_2_highfreq_calendar_arbitrage/ctp_example_support.py'),
):
    module_name = 'direct_inert_candidate_' + label
    module_path = QA / rel
    direct_spec = importlib.util.spec_from_file_location(module_name, module_path)
    direct_module = importlib.util.module_from_spec(direct_spec)
    sys.modules[module_name] = direct_module
    direct_spec.loader.exec_module(direct_module)
    assert callable(direct_module.load_dotenv_if_available)
    state['direct_no_fake_dotenv_imports'].append(str(module_path))
    sys.modules.pop(module_name, None)

# Replay the focused fake tests from the source tree copy.'''
if anchor not in text:
    raise SystemExit('direct import anchor not found')
text = text.replace(anchor, insert, 1)
text = text.replace("        'credential_env_values_read': False,", "        'credential_env_values_read': False,\n        'direct_no_fake_dotenv_imports': state['direct_no_fake_dotenv_imports'],")
path.write_text(text, encoding='utf-8')
