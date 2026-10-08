"""Fixed standalone R3 Windows candidate entry. Run with Python -I -S -B FILE.

`doctor` and `source-digest` are offline. `preview` performs the fixed fresh
read-only Demo snapshot; the initial direct/all-off preview accepts no price or
quantity and derives its candidate from that snapshot. `execute` requires the
exact confirmation and explicit price/quantity. Only reviewed source bytes may
be supplied as --source-sha256; a digest is a local operator pin, not a provider
attestation or release approval.
"""

import argparse
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def _require(value, reason):
    if not value:
        raise ValueError(reason)


STABLE_CLAIM_DIRECTORY_REF = (
    "binance-roundtrip-claims"
)
OPTIONAL_POLICY_PACKET_SCHEMA = "iteration41.optional-owner-root-packet.v1"


def build_argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("doctor", "source-digest", "preview", "execute"))
    parser.add_argument("--config")
    parser.add_argument("--env-file")
    parser.add_argument("--output")
    parser.add_argument("--source-sha256")
    parser.add_argument("--confirm")
    parser.add_argument("--transport", choices=("direct", "gateway_zmq"))
    parser.add_argument("--execution", action="store_true")
    parser.add_argument("--risk", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument(
        "--component-mode", choices=("execution", "risk", "monitor"), help=argparse.SUPPRESS
    )
    parser.add_argument("--optional-policy-packet")
    parser.add_argument("--operator-controls", action="store_true")
    return parser


def selection_from_args(args):
    from backtrader_runtime.certification_optional_topology import OptionalTopologySelection

    _require(getattr(args, "component_mode", None) is None, "legacy_component_mode_removed")
    _require(args.transport in {"direct", "gateway_zmq"}, "explicit_transport_required")
    _require(
        all(type(getattr(args, name)) is bool for name in ("execution", "risk", "monitor")),
        "optional_selection_flags_invalid",
    )
    return OptionalTopologySelection(
        args.transport,
        execution=args.execution,
        risk=args.risk,
        monitor=args.monitor,
    )


def _read_protected_packet(path, private, *, maximum=65536):
    """Read an explicit root-owned JSON packet through one owner-only handle."""
    path = private._path(Path(path))
    api = private._api()
    with _credential_ancestor_locks(path, private), _locked_readonly_file(
        path, private, api
    ) as (handle, identity):
        api.verify_acl(handle, api.current_sid())
        raw = _read_bounded_handle(api, handle, maximum)
        _require(
            _locked_file_identity(api, handle, private) == identity,
            "optional_policy_packet_changed",
        )
        api.verify_acl(handle, api.current_sid())
    return raw


def _parse_optional_policy_packet(raw, *, selection, plan, source_digest, optional_digest,
                                  owner_digest, plan_digest, budget_digest, claim_directory):
    from backtrader_runtime.certification_binance_roundtrip_r3 import strict_json
    from backtrader_runtime.certification_optional_owner_integration import (
        OptionalOwnerPolicyPreflightContext,
        REPLACEMENT_AUTHORIZATION_REF,
        is_replacement_client_order_id,
        is_supported_authorization_ref,
    )

    value = strict_json(raw)
    keys = {
        "schema",
        "expected_policy_sha256",
        "stable_claim_directory_ref",
        "case_id",
        "account_scope",
        "credential_binding_ref",
        "producer_source_digest",
        "optional_source_digest",
        "owner_source_digest",
        "plan_digest",
        "budget_digest",
        "selection",
    }
    _require(type(value) is dict and set(value) == keys, "optional_policy_packet_shape")
    _require(
        value["schema"] == OPTIONAL_POLICY_PACKET_SCHEMA
        and type(value["expected_policy_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["expected_policy_sha256"]) is not None
        and value["stable_claim_directory_ref"] == STABLE_CLAIM_DIRECTORY_REF,
        "optional_policy_packet_binding",
    )
    _require(
        Path(claim_directory.path).resolve() == (
            Path(_known_local_app_data())
            / "Codex"
            / "Backtrader"
            / "Iteration41"
            / "binance-roundtrip-claims"
        ).resolve(),
        "stable_claim_directory_mismatch",
    )
    _require(is_supported_authorization_ref(plan.authorization_ref), "permanent_grant_mismatch")
    if plan.authorization_ref == REPLACEMENT_AUTHORIZATION_REF:
        _require(
            is_replacement_client_order_id(plan.client_order_id),
            "replacement_client_id_not_fresh_uuid4",
        )
    _require(
        raw
        == json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii"),
        "optional_policy_packet_not_canonical",
    )
    _require(
        type(value["selection"]) is dict and value["selection"] == selection.document(),
        "optional_policy_packet_selection_mismatch",
    )
    _require(
        value["producer_source_digest"] == source_digest
        and value["optional_source_digest"] == optional_digest
        and value["owner_source_digest"] == owner_digest
        and value["plan_digest"] == plan_digest
        and value["budget_digest"] == budget_digest,
        "optional_policy_packet_source_or_plan_mismatch",
    )
    context = OptionalOwnerPolicyPreflightContext(
        case_id=value["case_id"],
        account_scope=value["account_scope"],
        credential_binding_ref=value["credential_binding_ref"],
        producer_source_digest=value["producer_source_digest"],
        optional_source_digest=value["optional_source_digest"],
        owner_source_digest=value["owner_source_digest"],
        plan_digest=value["plan_digest"],
        budget_digest=value["budget_digest"],
        selection=selection,
        authorization_ref=plan.authorization_ref,
    )
    _require(type(context.case_id) is str, "optional_policy_case_binding")
    return context, value["expected_policy_sha256"]


def _bootstrap():
    _require(
        sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
        "isolated_python_required",
    )
    root = Path(__file__).absolute().parent
    path = root / "certification_roundtrip_r3_bootstrap.py"
    name = "backtrader_runtime.certification_roundtrip_r3_bootstrap"
    _require(
        "backtrader_runtime" not in sys.modules and name not in sys.modules,
        "preloaded_runtime_forbidden",
    )
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module, module.snapshot(root)


def protected_env(path, selected_ref, private):
    """One handle, no write/delete sharing, exact owner DACL, bounded read."""
    _require(os.name == "nt", "windows_candidate_required")
    path = private._path(Path(path))
    _require(path.name == ".env", "explicit_env_file_required")
    api = private._api()
    with _require_ignored_env(path, private):
        handle = api.CreateFileW(
            str(path), 0x80000000 | 0x20000 | 0x80, 1, None, 3, 0x02200000, None
        )
        _require(handle != private._INVALID_HANDLE, "credential_open_failed")
        try:
            identity = api.info(handle, directory=False)
            api.verify_acl(handle, api.current_sid())
            reader = api.kernel.ReadFile
            reader.argtypes = [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ]
            reader.restype = wintypes.BOOL
            buffer = ctypes.create_string_buffer(65537)
            count = wintypes.DWORD()
            _require(
                reader(handle, buffer, 65537, ctypes.byref(count), None) and count.value <= 65536,
                "credential_read_failed",
            )
            body = bytes(buffer.raw[: count.value])
            _require(api.info(handle, directory=False) == identity, "credential_identity_changed")
            api.verify_acl(handle, api.current_sid())
        finally:
            _require(api.CloseHandle(handle), "credential_close_failed")
    needed = {"BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET"}
    if selected_ref is not None:
        needed.add(selected_ref)
    values = {}
    for line in body.decode("utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key not in needed:
            continue
        _require(separator and key not in values, "credential_duplicate")
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    _require(set(values) == needed, "credential_missing")
    for key in ("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET"):
        _require(re.fullmatch(r"[A-Za-z0-9_-]{16,256}", values[key]), "credential_shape")
    return {
        "api_key": values["BINANCE_DEMO_API_KEY"],
        "secret": values["BINANCE_DEMO_SECRET"],
    }, values.get(selected_ref)


@contextmanager
def _credential_ancestor_locks(path, private):
    """Hold validated ancestors for a credential input, allowing repository roots.

    The output helper's ancestor walk rejects Git repositories by design. An
    explicitly selected ignored ``.env`` input can live in the repository, so
    this input-only walk keeps its handle/reparse checks without the output
    location policy.
    """
    api = private._api()
    with ExitStack() as stack:
        for ancestor in reversed(path.parents):
            stack.enter_context(api.opened(ancestor, directory=True, access=0x80))
        yield


def _locked_file_identity(api, handle, private, *, allow_hardlinks=False):
    value = private._FILE_INFO()
    _require(
        api.kernel.GetFileInformationByHandle(handle, ctypes.byref(value)),
        "credential_ignore_source_identity_unavailable",
    )
    _require(not value.attributes & 0x400, "credential_ignore_source_reparse")
    _require(not value.attributes & 0x10, "credential_ignore_source_type")
    _require(allow_hardlinks or value.links == 1, "credential_ignore_source_hardlink")
    return value.volume, (value.index_high << 32) | value.index_low


@contextmanager
def _locked_readonly_file(path, private, api, *, allow_hardlinks=False):
    path = private._path(Path(path))
    handle = api.CreateFileW(str(path), 0x80000000 | 0x20000 | 0x80, 1, None, 3, 0x02200000, None)
    _require(handle != private._INVALID_HANDLE, "credential_ignore_source_unavailable")
    try:
        identity = _locked_file_identity(api, handle, private, allow_hardlinks=allow_hardlinks)
        yield handle, identity
        _require(
            _locked_file_identity(api, handle, private, allow_hardlinks=allow_hardlinks)
            == identity,
            "credential_ignore_source_changed",
        )
    finally:
        _require(api.CloseHandle(handle), "credential_ignore_source_close_failed")


def _read_bounded_handle(api, handle, maximum):
    reader = api.kernel.ReadFile
    reader.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    reader.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(maximum + 1)
    count = wintypes.DWORD()
    _require(
        reader(handle, buffer, maximum + 1, ctypes.byref(count), None) and count.value <= maximum,
        "credential_ignore_source_read_failed",
    )
    return bytes(buffer.raw[: count.value])


def _git_executable(private):
    found = shutil.which("git.exe") or shutil.which("git")
    _require(type(found) is str and found, "credential_ignore_git_unavailable")
    path = private._path(Path(found).absolute())
    _require(path.name.lower() == "git.exe", "credential_ignore_git_unavailable")
    return path


@contextmanager
def _require_ignored_env(path, private):
    """Hold the selected repo paths while proving the root .env is ignored."""
    path = private._path(Path(path))
    _require(path.name == ".env", "explicit_env_file_required")
    root = path.parent
    api = private._api()
    git_marker = private._path(root / ".git")
    ignore_file = private._path(root / ".gitignore")
    _require(os.path.lexists(git_marker), "credential_git_root_required")
    git_path = _git_executable(private)
    with _credential_ancestor_locks(path, private), ExitStack() as stack:
        # This candidate accepts only a regular .git directory, not a worktree
        # pointer file or a reparse point that redirects repository metadata.
        stack.enter_context(api.opened(git_marker, directory=True))
        ignore_handle, _ = stack.enter_context(_locked_readonly_file(ignore_file, private, api))
        rules = _read_bounded_handle(api, ignore_handle, 65536)
        _require(b".env" in rules.splitlines(), "credential_ignore_rule_missing")
        with _credential_ancestor_locks(git_path, private), _locked_readonly_file(
            git_path, private, api, allow_hardlinks=True
        ) as (git_handle, git_identity):
            env = {
                key: os.environ[key]
                for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
                if key in os.environ
            }
            env.update(
                GIT_CONFIG_NOSYSTEM="1",
                GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_COUNT="2",
                GIT_CONFIG_KEY_0="core.fsmonitor",
                GIT_CONFIG_VALUE_0="false",
                GIT_CONFIG_KEY_1="core.excludesFile",
                GIT_CONFIG_VALUE_1=os.devnull,
                GIT_OPTIONAL_LOCKS="0",
                GIT_TERMINAL_PROMPT="0",
            )
            process = None
            try:
                process = subprocess.Popen(
                    [
                        str(git_path),
                        "-C",
                        str(root),
                        "check-ignore",
                        "--quiet",
                        "--",
                        ".env",
                    ],
                    cwd=str(root),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                returncode = process.wait(timeout=3)
            except Exception:
                if process is not None and process.poll() is None:
                    try:
                        process.kill()
                        process.wait(timeout=0.4)
                    except Exception:
                        pass
                raise ValueError("credential_ignore_check_failed") from None
            _require(returncode == 0, "credential_file_not_ignored")
            _require(
                _locked_file_identity(api, git_handle, private, allow_hardlinks=True)
                == git_identity,
                "credential_ignore_git_changed",
            )
        yield


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _known_local_app_data():
    folder = _GUID(
        0xF1B32785,
        0x6FBA,
        0x4FCF,
        (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91),
    )
    result = ctypes.POINTER(ctypes.c_wchar)()
    get_path = ctypes.windll.shell32.SHGetKnownFolderPath
    get_path.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_wchar)),
    ]
    get_path.restype = ctypes.c_long
    _require(
        get_path(ctypes.byref(folder), 0, None, ctypes.byref(result)) == 0,
        "local_app_data_unavailable",
    )
    try:
        path = Path(ctypes.wstring_at(result))
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(ctypes.cast(result, ctypes.c_void_p))
    _require(path.is_absolute() and path.is_dir(), "local_app_data_unavailable")
    return path


def _open_private_directory(path, private):
    path = private._path(Path(path))
    api = private._api()
    with private._ancestors(path), api.opened(path, directory=True) as handle:
        identity = api.info(handle, directory=True)
        api.verify_acl(handle, api.current_sid(), directory=True)
    return private.PrivateArtifactDirectory(path, *identity)


def _private_directory(path, private):
    if os.path.lexists(path):
        return _open_private_directory(path, private), False
    try:
        return private.create_private_directory(path), True
    except Exception:
        if os.path.lexists(path):
            return _open_private_directory(path, private), False
        raise


def _read_claim_root_marker(path, private):
    path = private._path(Path(path))
    api = private._api()
    with private._ancestors(path):
        handle = api.CreateFileW(
            str(path), 0x80000000 | 0x20000 | 0x80, 1, None, 3, 0x02200000, None
        )
        _require(handle != private._INVALID_HANDLE, "claim_root_marker_unavailable")
        try:
            identity = api.info(handle, directory=False)
            api.verify_acl(handle, api.current_sid())
            reader = api.kernel.ReadFile
            reader.argtypes = [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ]
            reader.restype = wintypes.BOOL
            buffer = ctypes.create_string_buffer(4097)
            count = wintypes.DWORD()
            _require(
                reader(handle, buffer, 4097, ctypes.byref(count), None) and count.value <= 4096,
                "claim_root_marker_unavailable",
            )
            _require(api.info(handle, directory=False) == identity, "claim_root_marker_changed")
            api.verify_acl(handle, api.current_sid())
            return bytes(buffer.raw[: count.value])
        finally:
            _require(api.CloseHandle(handle), "claim_root_marker_close_failed")


@contextmanager
def _locked_shared_codex_directory(path, private):
    """Hold the existing shared Codex container without imposing a private DACL."""
    path = private._path(Path(path))
    api = private._api()
    # The KnownFolder path and every ancestor stay open without FILE_SHARE_DELETE;
    # the Codex handle below also verifies its directory identity and reparse state.
    with private._ancestors(path), api.opened(path, directory=True) as handle:
        identity = api.info(handle, directory=True)
        try:
            yield
        finally:
            _require(
                api.info(handle, directory=True) == identity,
                "claim_root_container_changed",
            )


def _stable_claim_directory(private, ledger_type):
    base = private._path(Path(_known_local_app_data()))
    codex_path = base / "Codex"
    if not os.path.lexists(codex_path):
        # New container directories are still born with the protected descriptor.
        _private_directory(codex_path, private)

    with _locked_shared_codex_directory(codex_path, private):
        root = codex_path
        for name in ("Backtrader", "Iteration41"):
            root = root / name
            _private_directory(root, private)
        marker_name = "binance-roundtrip-claims-root.json"
        marker_path = root / marker_name
        claims_path = root / "binance-roundtrip-claims"
        marker_expected = json.dumps(
            {"name": claims_path.name, "schema": "1", "purpose": "one-shot-binance-demo-actions"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if os.path.lexists(marker_path):
            _require(
                _read_claim_root_marker(marker_path, private) == marker_expected,
                "claim_root_marker_invalid",
            )
            directory = _open_private_directory(claims_path, private)
            return directory, False
        _require(not os.path.lexists(claims_path), "claim_root_marker_missing")
        directory, created = _private_directory(claims_path, private)
        _require(created, "claim_root_marker_race")
        ledger = ledger_type(directory, allow_initialize=True)
        ledger.close()
        parent = _open_private_directory(root, private)
        parent.write_bytes(marker_name, marker_expected)
        return directory, False


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    session = None
    try:
        boot, sources = _bootstrap()
        source_digest = boot.digest(sources)
        if args.mode == "source-digest":
            print(
                json.dumps(
                    {
                        "source_sha256": source_digest,
                        "source_files": {
                            k + ".py": hashlib.sha256(v).hexdigest() for k, v in sources.items()
                        },
                    }
                )
            )
            return 0
        if args.mode == "doctor":
            print(
                json.dumps(
                    {
                        "result": "OFFLINE_DOCTOR",
                        "provider_preflight_started": False,
                        "fixed_scope": "BTCUSDT_BUY_LONG_GTC_100_USDT_NOTIONAL",
                        "automatic_close": False,
                        "strict_cases_passed": 0,
                        "source_sha256": source_digest,
                    }
                )
            )
            return 0
        _require(args.source_sha256 == source_digest, "source_pin_mismatch")
        _require(args.component_mode is None, "legacy_component_mode_removed")
        _require(args.config and args.env_file and args.output, "explicit_paths_required")
        _require(os.name == "nt", "windows_candidate_required")
        boot.install(sources, source_digest)
        from backtrader_runtime.certification_binance_roundtrip_r3 import (
            LiveRoundtripR3,
            Plan,
            PersistentActionClaimLedger,
            account_scope_for_credentials,
            credential_binding_ref,
            direct_budget_digest,
            fixed_limit_command_and_budget,
            read_only_preview_budget,
            strict_json,
            validate_risk_policy_document,
        )
        from backtrader_runtime.certification_optional_topology import (
            OptionalTopologySelection,
        )
        from backtrader_runtime import certification_roundtrip_private as private
        from backtrader_runtime import certification_roundtrip_network as network

        with Path(args.config).open("rb") as stream:
            raw = stream.read(16385)
        _require(len(raw) <= 16384, "plan_size")
        config = strict_json(raw)
        _require(type(config) is dict, "config_shape")
        base_keys = {"plan", "network_profile", "proxy_env_ref"}
        selection = selection_from_args(args)
        uses_risk = selection.risk
        _require(
            set(config) == (base_keys | {"risk_policy"} if uses_risk else base_keys),
            "config_shape",
        )
        risk_policy_document = (
            validate_risk_policy_document(config["risk_policy"]) if uses_risk else None
        )
        binding = network.validate_network_binding(
            config["network_profile"], config["proxy_env_ref"]
        )
        plan = Plan(**config["plan"])
        execute = args.mode == "execute"
        _require(
            not execute or args.confirm == "BINANCE_DEMO_BTCUSDT_BUY_LONG_GTC_MAX_100_USDT_ONCE",
            "exact_confirmation_required",
        )
        _require(execute or args.confirm is None, "preview_cannot_confirm_write")
        # Validate everything public before the sole protected credential read.
        _require(args.transport is not None, "explicit_transport_required")
        _require(not args.operator_controls or selection.monitor, "operator_controls_require_monitor")
        initial_read_only_preview = (
            args.mode == "preview"
            and selection == OptionalTopologySelection("direct")
            and plan.price is None
            and plan.quantity is None
        )
        if initial_read_only_preview:
            _require(args.optional_policy_packet is None, "write_policy_forbidden_for_preview")
            _require(not args.operator_controls, "operator_controls_forbidden_for_preview")
            preview_budget, preview_budget_digest = read_only_preview_budget(
                plan, selection, source_digest
            )
            directory = private.create_private_directory(Path(args.output))
            directory.write_json(
                "read-only-preview-budget.json",
                {"sha256": preview_budget_digest, "document": preview_budget},
            )
            credentials, proxy_url = protected_env(args.env_file, binding["proxy_env_ref"], private)
            route = network.parse_network_profile(**binding, proxy_url=proxy_url)
            directory.write_json(
                "binding.json",
                {
                    "plan": plan.document(),
                    "source_sha256": source_digest,
                    "network_binding": binding,
                    "endpoint_fingerprint": route.endpoint_fingerprint,
                    "read_only_preview_budget_sha256": preview_budget_digest,
                },
            )
            session = LiveRoundtripR3(
                directory,
                plan,
                credentials,
                {**binding, "proxy_url": proxy_url},
                execute=False,
                selection=selection,
            )
            report = session.run_once()
            session.close()
            session = None
            report["read_only_preview_budget"] = {
                "sha256": preview_budget_digest,
                "document": preview_budget,
            }
            directory.write_json("result.json", report)
            public = {
                k: report[k]
                for k in (
                    "result",
                    "reason",
                    "source_kind",
                    "order_cleanup",
                    "position_cleanup",
                    "fill_exposure_requires_review",
                    "strict_cases_passed",
                )
            }
            if "candidate" in report:
                public["candidate"] = report["candidate"]
            if "l04_local_validation" in report:
                public["l04_local_validation"] = report["l04_local_validation"]
            public["read_only_preview_budget_sha256"] = preview_budget_digest
            print(json.dumps(public))
            return 0 if report["result"] == "READ_ONLY_PREVIEW" else 2

        _require(args.optional_policy_packet, "explicit_optional_policy_packet_required")
        from backtrader_runtime import certification_optional_admission_policy as admission
        from backtrader_runtime import certification_optional_owner_integration as optional_owner
        from backtrader_runtime.certification_optional_topology import (
            optional_composition_source_digest,
        )

        command, budget = fixed_limit_command_and_budget(plan)
        plan_digest = PersistentActionClaimLedger._plan_digest(plan, source_digest)
        budget_digest = direct_budget_digest(budget)
        optional_digest = optional_composition_source_digest()
        owner_digest = optional_owner.optional_owner_source_digest()

        directory = private.create_private_directory(Path(args.output))
        claim_directory, initialize_claim_ledger = _stable_claim_directory(
            private, PersistentActionClaimLedger
        )
        stable_claim_directory = admission.bind_stable_claim_directory(claim_directory)
        packet_raw = _read_protected_packet(args.optional_policy_packet, private)
        preflight_context, expected_policy_sha256 = _parse_optional_policy_packet(
            packet_raw,
            selection=selection,
            plan=plan,
            source_digest=source_digest,
            optional_digest=optional_digest,
            owner_digest=owner_digest,
            plan_digest=plan_digest,
            budget_digest=budget_digest,
            claim_directory=claim_directory,
        )
        prevalidated_policy = optional_owner.prevalidate_optional_owner_policy(
            stable_claim_directory,
            expected_policy_sha256=expected_policy_sha256,
            expected_context=preflight_context,
            operation_confirmation=optional_owner.OPERATION_CONFIRMATION,
        )
        # The exact selected SDK objects and dependency closure are loaded
        # before credential access; constructors remain after account binding.
        sdk_set = optional_owner.import_verified_sdk_set(prevalidated_policy)
        credentials, proxy_url = protected_env(args.env_file, binding["proxy_env_ref"], private)
        actual_context = optional_owner.OptionalOwnerPolicyContext(
            case_id=preflight_context.case_id,
            account_scope=account_scope_for_credentials(credentials),
            credential_binding_ref=credential_binding_ref(credentials),
            owner_id=plan.owner_id,
            run_id=plan.run_id,
            action_id=plan.action_id,
            cancel_action_id=plan.cancel_action_id,
            client_order_id=plan.client_order_id,
            authorization_ref=plan.authorization_ref,
            producer_source_digest=source_digest,
            optional_source_digest=optional_digest,
            owner_source_digest=owner_digest,
            plan_digest=plan_digest,
            budget_digest=budget_digest,
            selection=selection,
        )
        verified_policy = optional_owner.bind_optional_owner_policy_context(
            prevalidated_policy, actual_context
        )
        sdk_set.bind_policy(verified_policy)
        sdk_set.guard()
        risk_policy = None
        if selection.risk:
            with sdk_set.import_scope():
                risk_policy = optional_owner.build_verified_risk_policy(
                    risk_policy_document, sdk_set
                )
            sdk_set.guard()
        route = network.parse_network_profile(**binding, proxy_url=proxy_url)
        # Endpoint and fingerprint remain in this private invocation only.
        directory.write_json(
            "binding.json",
            {
                "plan": plan.document(),
                "source_sha256": source_digest,
                "network_binding": binding,
                "endpoint_fingerprint": route.endpoint_fingerprint,
            },
        )
        session = LiveRoundtripR3(
            directory,
            plan,
            credentials,
            {**binding, "proxy_url": proxy_url},
            execute=execute,
            selection=selection,
            risk_policy_document=risk_policy_document,
            optional_policy=verified_policy,
            sdk_set=sdk_set,
            operator_controls=args.operator_controls,
            optional_preflight_source_digest=optional_digest,
            claim_directory=claim_directory if execute else None,
            initialize_claim_ledger=initialize_claim_ledger if execute else False,
        )
        if risk_policy is not None:
            session._bind_risk_policy(risk_policy)
        report = session.run_once()
        session.close()
        session = None
        directory.write_json("result.json", report)
        # No account, proxy, order, path, raw body or request identifiers leave
        # the protected archive in stdout.
        public = {
            k: report[k]
            for k in (
                "result",
                "reason",
                "source_kind",
                "order_cleanup",
                "position_cleanup",
                "fill_exposure_requires_review",
                "strict_cases_passed",
            )
        }
        if args.mode == "preview" and "candidate" in report:
            public["candidate"] = report["candidate"]
        print(json.dumps(public))
        return (
            0 if report["result"] in {"READ_ONLY_PREVIEW", "LIMIT_CANCEL_ROUNDTRIP_OBSERVED"} else 2
        )
    except Exception:
        print(
            json.dumps(
                {
                    "result": "BLOCKED_OR_UNKNOWN",
                    "reason": "roundtrip_not_completed",
                    "strict_cases_passed": 0,
                    "automatic_retry": False,
                }
            )
        )
        return 2
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
