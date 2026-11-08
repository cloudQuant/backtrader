GAP: test_transport_protocols_are_structural_and_service_protocol_import_is_stdlib_only uses sys.executable -S -c; -S suppresses sitecustomize so child origin/offline audit is unavailable. Static exact script: "import sys; import bt_api_base.service_protocol; assert not {'zmq', 'pydantic', 'numpy'} & set(sys.modules)"
script_sha256=872bc3a4ccbb71415eb6bafc6addd7f75636ea16bd8778980def3d4484658f0b
The test uses subprocess.run(check=True): a passing test establishes child exit code 0, not a child-origin audit. The exact script contains no native factory or network call.
