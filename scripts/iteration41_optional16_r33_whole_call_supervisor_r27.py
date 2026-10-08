"""Closed R27 outer supervisor for the sealed R19 Optional16 route.

The parent creates one fresh isolated R12 process under a kill-on-close Job.
It creates that process suspended, assigns it to the Job, observes the retained
process handle with the separately pinned image leaf, and only then resumes the
initial thread.  The image leaf does not establish suspension, Job membership,
or physical source custody; those are separate caller-owned steps.

All ROOT and native switches are closed on disk.  Root must independently hold
and post-verify the exact source/software closure, fill the reviewed activation
slots in memory, and enable the pinned image leaf before calling ``main``.
Source/fake tests replace only the process/native observation leaves.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import types


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"

ROOT_SELF_PATH = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py"
ROOT_TEST_PATH = (
    ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
)
ROOT_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r27-source-candidate-2026-10-08"
)
ROOT_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r27-independent-review-2026-10-08"
)
ROOT_SELF_SHA256 = None
ROOT_TEST_SHA256 = None
ROOT_PACKET_PINS = {
    "source-bundle.zip": None,
    "source-index.json": None,
    "source-pins.json": None,
    "checkpoint.json": None,
}
ROOT_PACKET_AUX_PINS = {"README.md": None, "qa/qa-summary.json": None}
ROOT_REVIEW_PINS = {
    "review.json": None,
    "review-bundle.zip": None,
    "review-index.json": None,
    "review-checkpoint.json": None,
    "README.md": None,
}
ROOT_ACTUAL_ENABLED = False
ROOT_REVIEW_READY = False
ROOT_REVIEWED_ACTIVATION = False
ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED = False
ROOT_NATIVE_ENABLED = False

ROOT_CONTROL = Path(r"D:\temp\iteration41-optional16-r33-whole-call-control-r27")
ROOT_ONCE_PATH = ROOT_CONTROL / "whole-call-once.claim"
ROOT_OUTPUT_PATH = (
    EVIDENCE / "iteration41-optional16-r33-whole-call-r27-root-observation-2026-10-08.json"
)

R27_INVOKE_SOURCE = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
R27_INVOKE_SHA256 = None
R27_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
R27_TEST_SHA256 = None
R22_WHOLE_SOURCE = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r22.py"
R22_WHOLE_SHA256 = "134fa7e81e4ede8fe6d6dcf14e0ab91013c31265018a2bdc693562efa9962d0d"
R22_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r22_source_fake.py"
R22_TEST_SHA256 = "f98eaefa489673caabfba8d29508f866fff9d46af87365093865da168503c724"
R22_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r22-source-candidate-2026-10-08"
)
R22_PACKET_PINS = {
    "source-bundle.zip": "5582d5f498d5a7afe1bcb214200b3a72f3f3fbd6e8ae9385ec2fe74a58f2423f",
    "source-index.json": "c4c3fdbbb9b74159e199c5bf677c179b15e47e89f6cc6756be475171e5ef2ecd",
    "source-pins.json": "df54c363349ceaa89fcceccf3d36f7ea9f096fd4ab70944b716e858b33f78216",
    "checkpoint.json": "45f976c80441bbf40e5e1c2203edd14930245c3a43b811fb77db35b4af87035c",
    "README.md": "4cfc424955b50274866ab1befa440fd3108d00e9bb6a06f247c753244ee885c3",
    "qa/qa-summary.json": "3ba4db44a68314444f62c632d58ee19af55e9f81e57cf925020629120f1c3668",
}
R22_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r22-independent-review-2026-10-08"
)
R22_REVIEW_PINS = {
    "review.json": "e68bf5657b6077e0fc1d19608ae5933985e0d4c56fc0fb79fe9e0e3b1c23c68a",
    "review-bundle.zip": "88ce17c185ee672d0f1ae25a95402e54d0ef031506005403a1544a1c52e1a751",
    "review-index.json": "975c781c7296a9b6a7860ce0563e52a308b83828b435166498f1bd84696cd621",
    "review-checkpoint.json": "de0bce0600c023ca2e134de43e0a4d5759329e833c7fb272c0a5c2f2c4a73c05",
    "README.md": "5951acdf5bec4c2ae5b7d897f1c8f520440c43cf69c58375c7022fda8530b8c4",
}
R24_WHOLE_SOURCE = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r24.py"
R24_WHOLE_SHA256 = "00f7e5ca4bbac9651165a53492e60f9021f3a9b5953c60cb6102ad824147603a"
R24_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r24_source_fake.py"
R24_TEST_SHA256 = "cc18dc20745e0f03ba700d96998bce7df5942d77c4499f4e0853fd2f4a9c9c58"
R24_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r24-source-candidate-2026-10-08"
)
R24_PACKET_PINS = {
    "source-bundle.zip": "b21ebad023de75fbf6dd989a0e050f312a5c7afa0ceca5d4076c26e6e5285572",
    "source-index.json": "14710605c7304a1b666c044feb9ae9a4775e7b28abfbf5ea2349c66a4cb1f8f2",
    "source-pins.json": "3089e9fd9e97d625ee8f7a3015113c5122bf1f8d39fd63818dbf4c610c10f22a",
    "checkpoint.json": "b1ea8c656a353405bb257d68061bc2b8f44bb202952ec1e6a075fdb8c9ef75d5",
    "README.md": "8a487bc0049a34d58c0bdba7ada21aeb65662c7956f4cd726398667a5e48d86e",
    "qa/qa-summary.json": "0550277f5de4866aca51b5bd609865e7cf2d5be56c9f6b422400a538af773de4",
}
R24_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r24-independent-review-2026-10-08"
)
R24_REVIEW_PINS = {
    "review.json": "1a122029f20e0504a90e1d677cca565d03251bd091580dce0822f0f9ba98c2aa",
    "review-bundle.zip": "ffec05d5b1675b23189bbf8275fca9e235cfd7d8dc213e04f8d1b7ebea71b546",
    "review-index.json": "069570920b0a9e0d08114b59345a5f4603d924c7b817757151a758e64ab0e4b2",
    "review-checkpoint.json": "418b0055a4dfec0834e3819f7ab92b80c272b2874dc5142f0ba7cc813ddfa543",
    "README.md": "0fc771fe55fb13f33ac8385d690877de3dc5a64ac30e936da17fd793d0c282d8",
}
R25_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r25-source-candidate-2026-10-08"
)
R25_PACKET_PINS = {
    "source-bundle.zip": "bfdeb4969b9758c01f31b7c1ca1e0f402b17165491d988a124738fe96818c3ec",
    "source-index.json": "d3555c3c44e6a889b7a494b79565188ff52426beb4f82a77f5571d2f93700893",
    "source-pins.json": "9fc445a698748af5da01c2dc80212bd664d717c32925c963bd43e6357ee65fcf",
    "checkpoint.json": "7264173695fa1eff59c1c607416f11375a121fb99a4bd02adcb4d7f624254eb5",
    "README.md": "55af4d088bec62fcdd427732175113ae5a62cfb10a68feb4e2cb3ccde03fe5a8",
    "qa/qa-summary.json": "102c7c88edf012b601a80793266842604ed1720657704bc3c06cc1f26dede5c1",
}
R25_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r25-independent-review-2026-10-08"
)
R25_REVIEW_PINS = {
    "review.json": "beb73455618e11f419c6dfeb1e2fe1c438571eec2d972d9328c7232826e3e284",
    "review-bundle.zip": "c950ce45cd97cab22d1cef7b3bf89d13598cfc17ac04d5e1c2ed6abbbffc2192",
    "review-index.json": "f37c85165bcbbb0671dd8c1285ff345961ee7da18d2bea4ab14cc5a2de4eeb93",
    "review-checkpoint.json": "49a9caa1dd3bc1de740418290291477ede4ed1efef31c7eabf85bfd9121ad337",
    "README.md": "b50e9d0c6c75c27dadfd6d6c57fb38eea6be4f3e0624be7818c84d46d197bb16",
}
R19_DRIVER_SOURCE = ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"
R19_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r19_source_fake.py"
R19_TEST_SHA256 = "482573a175cd54b7607a87e8da2bb995b845fc0a946d7d7bfdfd490f2488d88c"
R19_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r19_binding.py"
R19_BINDING_HELPER_SHA256 = "1774b2776c9c03c0e10574fda4f58093f3c2947d902d78c2d41bac9d4c47ba58"
R19_WHOLE_SOURCE = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r19.py"
R19_WHOLE_SHA256 = "80c6e936e99ba8da781c77ca2c3a4573a2462fe988de402b59cf47e439d1d91f"
R19_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
)
R19_PACKET_PINS = {
    "source-bundle.zip": "9ee3054927823b6c746058a291aacdb21b2df65f9a6660e7acdca139c1095626",
    "source-index.json": "dd3e008f645b598e118c03cd48f5dc07618605c9c826b776e0a17e3d41906263",
    "source-pins.json": "db243608a6b5fd651d97e508c4ae79efabe0c82bef782815f30a381b4d8597b4",
    "checkpoint.json": "1c09f6660ab7c470a65d0843ae98837dc8d5dda73a0aa772d6743c8a367f5da3",
    "README.md": "f1d5788f7b18507fd7b6f19b0632b2cd830cfac88ec20ed0e1116012ad83acc0",
    "qa/qa-summary.json": "818c0bac5dc99b6494a5ac77fd514419d8b3bcb5cb27afe1bd851a1ba62c0710",
}
R19_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
)
R19_REVIEW_PINS = {
    "review.json": "6a5f8583172baf30f9252ad8f53b421a6e6990c0fae63299708e7dd4d8f2cba7",
    "review-bundle.zip": "e78e4eea04a2733f25803f26aa2b9b1880cf027cc2e4a33581f004275cc04099",
    "review-index.json": "9bca667b3c713f767b5ae28ca017ea9d3667f95fe72bbc6127349b7e9e9c0b94",
    "review-checkpoint.json": "6c279228ec6523989c71fc1a06f779f316261df657856fce4b5bc842a73eb634",
    "README.md": "7de172f561ebcc0ed51fee854e15bef47d20eca693b0f00390a23f3d16e6caf5",
}
JOB_SOURCE = ROOT / "scripts/iteration41_okx_l03_l04_v4_root_launcher.py"
JOB_SOURCE_SHA256 = "0b8076f4cd8aa4419a29a0bbc3f1884e24c2610e2ba5b6cf2000c0cdf861c023"
IMAGE_LEAF_SOURCE = ROOT / "scripts/iteration41_suspended_child_image_r2.py"
IMAGE_LEAF_SHA256 = "3f14b2771a73e056b7902f48f65bfebbf17e93a62202a55f66de6ac3ff12d0cc"
IMAGE_LEAF_TEST = ROOT / "tests/unit/scripts/test_iteration41_suspended_child_image_r2.py"
IMAGE_LEAF_TEST_SHA256 = "a3e0389ef60214bc442cab731f50ef8c87322c14464c2aa5a60d505468e38b0e"
IMAGE_LEAF_PACKET = EVIDENCE / "iteration41-suspended-child-image-r2-source-fake-2026-10-06"
IMAGE_LEAF_PACKET_PINS = {
    "source-bundle.zip": "e809253214969f286d1f1672d36b1ee8e00c7c9d815da90a29fa2018d3fa4b18",
    "source-index.json": "a1c18972cd5f19fa9a912d40c5139a97ddfbc91ff7f13b9daff9ac69fd7892e0",
    "source-pins.json": "7d7c48bb0ce0633056fc5137bb6f4391a914313c7e3416ad22b96a5acd27bd23",
    "checkpoint.json": "b7087d45a86324abffb75fa49d7109f0019014a16a7aa276e269ef12c17b17c9",
    "README.md": "13dcf5da0709dd64236f3bfaa283e71d7fa031c7f09264395226f24fd94dfbfc",
    "qa-summary.json": "83d5ba67bd1380f2840d5d0dd25a14ffcab3f4acd5c7a5295db0e89a341b7abe",
}

FIXED_EXECUTABLE = "C:/anaconda3/python.exe"
R27_FRESH_PATHS = {
    "ROOT_CONTROL": r"D:\temp\iteration41-optional16-r33-root-held-activation-r27",
    "ROOT_SCRATCH": r"D:\temp\iteration41-optional16-r33-root-held-scratch-r27",
    "ROOT_DRIVER_CONTROL": r"D:\temp\iteration41-optional16-r33-root-control-r27",
    "ROOT_DRIVER_SCRATCH": r"D:\temp\iteration41-optional16-r33-matrix-scratch-r27",
    "ROOT_OUTPUT": str(EVIDENCE / "iteration41-optional16-r33-root-held-invocation-r27-2026-10-08"),
    "ROOT_PRECHECK_OUTPUT": str(
        EVIDENCE / "iteration41-optional16-r33-root-held-precheck-r27-2026-10-08"
    ),
}
R27_DRIVER_ACTIVE_PATH = Path(r"D:\temp\iteration41-optional16-r33-root-driver-r27.py")
ACTIVE_PUBLIC_PATH_COUNT = None
ACTIVE_SOFTWARE_PATH_COUNT = 5
ACTIVE_PATH_ALIAS_COUNT = None
INERT_PUBLIC_PATH_COUNT = None

WHOLE_CALL_SECONDS = 100.0
CLEANUP_SECONDS = 5.0
PARENT_DEADLINE_CLOCK_DOMAIN = "windows-cpython-3.11.5-monotonic-v1"
POLL_SECONDS = 0.05
STREAM_LIMIT = 65_536
CHILD_FRAME_LIMIT = 12_288
PAYLOAD_LIMIT = 8_192
_HASH_CHARS = frozenset("0123456789abcdef")
_LOCK_TYPE = type(threading.Lock())
_RETAINED: list[dict[str, object]] = []


def _r27_path_contract_ready() -> bool:
    expected = {
        "ROOT_CONTROL": r"D:\temp\iteration41-optional16-r33-root-held-activation-r27",
        "ROOT_SCRATCH": r"D:\temp\iteration41-optional16-r33-root-held-scratch-r27",
        "ROOT_DRIVER_CONTROL": r"D:\temp\iteration41-optional16-r33-root-control-r27",
        "ROOT_DRIVER_SCRATCH": r"D:\temp\iteration41-optional16-r33-matrix-scratch-r27",
        "ROOT_OUTPUT": str(
            EVIDENCE / "iteration41-optional16-r33-root-held-invocation-r27-2026-10-08"
        ),
        "ROOT_PRECHECK_OUTPUT": str(
            EVIDENCE / "iteration41-optional16-r33-root-held-precheck-r27-2026-10-08"
        ),
    }
    if type(R27_FRESH_PATHS) is not dict or expected != R27_FRESH_PATHS:
        return False
    if Path(r"D:\temp\iteration41-optional16-r33-root-driver-r27.py") != R27_DRIVER_ACTIVE_PATH:
        return False
    values = [Path(value) for value in R27_FRESH_PATHS.values()]
    values.extend((R27_DRIVER_ACTIVE_PATH, ROOT_CONTROL, ROOT_OUTPUT_PATH, R19_DRIVER_SOURCE))
    keys = [os.path.normcase(os.path.normpath(str(value))) for value in values]
    return len(keys) == len(set(keys))


_CHILD_BOOTSTRAP_BODY = r"""import hashlib, importlib.machinery, json, math, sys, time, types
MAX = 8192
def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate_key")
        out[key] = value
    return out
_R27_CHILD_PHASE = "child_payload"
raw = sys.stdin.buffer.read(MAX + 1)
if type(raw) is not bytes or not raw or len(raw) > MAX:
    raise SystemExit(2)
cfg = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
required = {"schema", "invoke", "driver", "counts", "fresh_paths", "parent_deadline_monotonic", "parent_deadline_domain"}
if type(cfg) is not dict or set(cfg) != required or cfg.get("schema") != "iteration41.optional16.r33.whole-call.r27-child-activation.v1":
    raise SystemExit(2)
deadline = cfg["parent_deadline_monotonic"]
now = time.monotonic()
if (sys.platform != "win32" or sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 11, 5)
        or type(deadline) is not float or type(now) is not float
        or cfg["parent_deadline_domain"] != "windows-cpython-3.11.5-monotonic-v1"
        or not math.isfinite(deadline) or not math.isfinite(now)
        or not 0.0 < deadline - now <= 100.0):
    raise SystemExit(2)
def digest(value):
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)
def pin_map(value, names):
    return type(value) is dict and set(value) == names and all(digest(v) for v in value.values())
invoke = cfg["invoke"]
invoke_keys = {"path", "sha256", "test_path", "test_sha256", "packet_dir", "packet_pins", "review_dir", "review_pins", "review_readme_sha256"}
if type(invoke) is not dict or set(invoke) != invoke_keys:
    raise SystemExit(2)
if (invoke["path"] != r"D:\source_code\backtrader\scripts\iteration41_optional16_r33_root_held_invoke_r27.py"
        or invoke["test_path"] != r"D:\source_code\backtrader\tests\unit\scripts\test_iteration41_optional16_r33_activation_r27_source_fake.py"
        or invoke["packet_dir"] != r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
        or invoke["review_dir"] != r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
        or not digest(invoke["sha256"]) or not digest(invoke["test_sha256"])
        or not pin_map(invoke["packet_pins"], {"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json", "README.md", "qa/qa-summary.json"})
        or not pin_map(invoke["review_pins"], {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"})
        or invoke["review_readme_sha256"] != invoke["review_pins"]["README.md"]):
    raise SystemExit(2)
driver = cfg["driver"]
expected_driver = {
    "path": r"D:\source_code\backtrader\scripts\iteration41_optional16_r33_root_driver_r19.py",
    "sha256": "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890",
    "test_path": r"D:\source_code\backtrader\tests\unit\scripts\test_iteration41_optional16_r33_activation_r19_source_fake.py",
    "test_sha256": "482573a175cd54b7607a87e8da2bb995b845fc0a946d7d7bfdfd490f2488d88c",
    "packet_dir": r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07",
    "review_dir": r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07",
    "active_path": r"D:\temp\iteration41-optional16-r33-root-driver-r27.py",
}
if (type(driver) is not dict or set(driver) != {
        "path", "sha256", "test_path", "test_sha256", "packet_dir", "packet_pins",
        "review_dir", "review_pins", "review_readme_sha256", "active_path"}
        or any(driver.get(key) != value for key, value in expected_driver.items())
        or not pin_map(driver.get("packet_pins"), {"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json", "README.md", "qa/qa-summary.json"})
        or not pin_map(driver.get("review_pins"), {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"})
        or driver.get("review_readme_sha256") != driver["review_pins"]["README.md"]):
    raise SystemExit(2)
counts = cfg["counts"]
if (type(counts) is not dict or set(counts) != {"inert_public_paths", "active_public_paths", "software_paths", "path_aliases"}
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["software_paths"] != 5 or counts["active_public_paths"] < counts["inert_public_paths"]):
    raise SystemExit(2)
expected_paths = {
    "ROOT_CONTROL": r"D:\temp\iteration41-optional16-r33-root-held-activation-r27",
    "ROOT_SCRATCH": r"D:\temp\iteration41-optional16-r33-root-held-scratch-r27",
    "ROOT_DRIVER_CONTROL": r"D:\temp\iteration41-optional16-r33-root-control-r27",
    "ROOT_DRIVER_SCRATCH": r"D:\temp\iteration41-optional16-r33-matrix-scratch-r27",
    "ROOT_OUTPUT": r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-root-held-invocation-r27-2026-10-08",
    "ROOT_PRECHECK_OUTPUT": r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-optional16-r33-root-held-precheck-r27-2026-10-08",
}
if cfg["fresh_paths"] != expected_paths:
    raise SystemExit(2)
_R27_CHILD_PHASE = "child_invoke_source"
path = invoke["path"]
try:
    source = open(path, "rb").read()
    test_source = open(invoke["test_path"], "rb").read()
    driver_source = open(driver["path"], "rb").read()
    driver_test = open(driver["test_path"], "rb").read()
except OSError:
    raise SystemExit(2)
if (hashlib.sha256(source).hexdigest() != invoke["sha256"]
        or hashlib.sha256(test_source).hexdigest() != invoke["test_sha256"]
        or hashlib.sha256(driver_source).hexdigest() != driver["sha256"]
        or hashlib.sha256(driver_test).hexdigest() != driver["test_sha256"]):
    raise SystemExit(2)
name = "_iteration41_optional16_r33_r27_supervised_child"
if name in sys.modules:
    raise SystemExit(2)
module = types.ModuleType(name)
module.__file__ = path
module.__package__ = ""
module.__cached__ = None
module.__loader__ = None
module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=path)
module.__verified_source_sha256__ = invoke["sha256"]
sys.modules[name] = module
exec(compile(source, path, "exec", dont_inherit=True), module.__dict__)
# The R27 invoke source carries the frozen R19 aggregate packet/review slots.
# Its own R27 candidate and review are pinned by this whole supervisor's
# separate outer fixed-input closure.
from pathlib import Path
for key, value in expected_paths.items():
    setattr(module, key, Path(value))
module.DRIVER_ACTIVE_PATH = Path(driver["active_path"])
_R27_CHILD_PHASE = "child_activation_binding"
result = module.bind_child_activation(cfg)
_R27_CHILD_PHASE = "child_activation_readiness"
if (type(result) is not dict or result.get("status") != "COMPLETE_CHILD_BINDING_VALIDATED"
        or module.activation_ready() is not True):
    raise SystemExit(2)
_R27_CHILD_PHASE = "child_invoke_main"
_R27_MAIN_RESULT = module.main(["--execute-r33-root-r5"])
if type(_R27_MAIN_RESULT) is not int or _R27_MAIN_RESULT not in (0, 2):
    raise RuntimeError("child_main_return_code_invalid")
_R27_EXPECTED_EXIT = True
raise SystemExit(_R27_MAIN_RESULT)
"""

# Static R21 RootEnvelopeError codes reachable from bind_child_activation.
_R27_BINDER_SAFE_CODES = frozenset(
    {
        "artifact_reader_invalid",
        "child_activation_payload_shape",
        "child_activation_schema_invalid",
        "child_counts_invalid",
        "child_counts_shape_invalid",
        "child_deadline_invalid",
        "child_fresh_paths_invalid",
        "driver_activation_readiness_failed",
        "driver_activation_readiness_lost",
        "driver_active_copy_mismatch",
        "driver_aggregate_helper_pin_invalid",
        "driver_aggregate_input_pin_invalid",
        "driver_aggregate_source_missing",
        "driver_artifact_reader_invalid",
        "driver_binding_invalid",
        "driver_binding_path_invalid",
        "driver_binding_shape_invalid",
        "driver_disk_activation_changed",
        "driver_disk_packet_pins_changed",
        "driver_disk_review_changed",
        "driver_disk_review_pins_changed",
        "driver_expected_counts_invalid",
        "driver_inert_public_map_invalid",
        "driver_inert_public_metadata_invalid",
        "driver_inert_public_pin_invalid",
        "driver_must_be_non_main",
        "driver_packet_pins_invalid",
        "driver_r5_active_map_shape",
        "driver_r5_review_invalid",
        "driver_review_pins_invalid",
        "driver_review_readme_pin_invalid",
        "driver_source_hash_invalid",
        "driver_source_not_frozen_r19",
        "driver_test_hash_invalid",
        "driver_test_not_frozen_r19",
        "fixed_module_alias_already_loaded",
        "invoke_activation_readiness_failed",
        "invoke_binding_path_invalid",
        "invoke_binding_shape_invalid",
        "invoke_packet_pins_invalid",
        "invoke_review_pins_invalid",
        "invoke_review_readme_pin_invalid",
        "invoke_source_hash_invalid",
        "invoke_source_path_invalid",
        "invoke_test_hash_invalid",
        "path_not_absolute",
        "path_shape",
        "path_text",
        "path_type",
        "r16_helper_hash_invalid",
        "r17_helper_hash_invalid",
        "r18_aggregate_helper_pin_invalid",
        "r18_helper_hash_invalid",
        "r19_helper_hash_invalid",
        "r2_inert_driver_closure_shape",
        "r2_inert_driver_defaults_changed",
    }
)
_R27_SOURCE_CUSTODY_CODES = frozenset(
    {
        "held_map_type",
        "path_type",
        "path_text",
        "path_not_absolute",
        "path_shape",
        "held_bytes_type",
        "held_path_bytes_conflict",
        "held_path_missing",
        "complete_held_source_mismatch",
        "root_review_gate_closed",
        "root_packet_pins_shape",
        "root_review_pins_shape",
        "aggregate_binding_helper_pin_mismatch",
        "r17_helper_pin_mismatch",
        "r16_helper_pin_mismatch",
        "r18_helper_pin_mismatch",
    }
)


_CHILD_ENTRY_PHASE_TO_CODE = {
    "child_payload": "child_payload_failure",
    "child_invoke_source": "child_invoke_source_failure",
    "child_activation_binding": "child_activation_binding_failure",
    "child_activation_readiness": "child_activation_readiness_failure",
    "child_invoke_main": "child_invoke_main_failure",
}


def _wrap_child_bootstrap(body: str) -> str:
    """Add a bounded error frame around the child entry without exception text."""
    code = (
        r"""import json, sys
_R27_CHILD_PHASE = "child_payload"
def _r27_exception_label(error):
    labels = {
        SystemExit: "SystemExit",
        OSError: "OSError",
        FileNotFoundError: "FileNotFoundError",
        PermissionError: "PermissionError",
        TimeoutError: "TimeoutError",
        RuntimeError: "RuntimeError",
        ValueError: "ValueError",
        TypeError: "TypeError",
        KeyError: "KeyError",
        UnicodeError: "UnicodeError",
        AssertionError: "AssertionError",
        AttributeError: "AttributeError",
        EOFError: "EOFError",
        ImportError: "ImportError",
        NameError: "NameError",
        IndexError: "IndexError",
        OverflowError: "OverflowError",
        ZeroDivisionError: "ZeroDivisionError",
        SystemError: "SystemError",
    }
    label = labels.get(type(error))
    if label is not None:
        return label
    if type(error).__name__ == "BindingError":
        return "BindingError"
    if type(error).__name__ == "_ParentDeadlineBlocked":
        return "_ParentDeadlineBlocked"
    _module = globals().get("module")
    if _module is not None and type(error) is getattr(_module, "RootEnvelopeError", None):
        return "RootEnvelopeError"
    return "UNOBSERVED"
def _r27_safe_source_code(error, phase):
    _module = globals().get("module")
    _error_type = getattr(_module, "RootEnvelopeError", None) if _module is not None else None
    _args = getattr(error, "args", None)
    if (phase == "child_activation_binding" and _error_type is not None
            and type(error) is _error_type and type(_args) is tuple and len(_args) == 1
            and type(_args[0]) is str and _args[0] in """
        + repr(_R27_BINDER_SAFE_CODES)
        + r"""):
        return _args[0]
    return """
        + repr(_CHILD_ENTRY_PHASE_TO_CODE)
        + r"""[phase]
def _r27_emit_entry_failure(error):
    phase = globals().get("_R27_CHILD_PHASE")
    if type(phase) is not str or phase not in """
        + repr(frozenset(_CHILD_ENTRY_PHASE_TO_CODE))
        + r""":
        phase = "child_payload"
    document = {
        "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
        "status": "ROOT_UNCERTAIN_RETAINED_NO_PARSE",
        "reason_code": "root_adapter_exception",
        "source_scope_released": False,
        "complete_custody_postverified": False,
        "source_custody_state": "NOT_ESTABLISHED",
        "source_scope_references_retained_until_root_process_exit": True,
        "complete_custody_retained_until_root_process_exit": False,
        "late_frame_parsed": False,
        "public_raw_saved": False,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "exception_diagnostic": {
            "phase": phase,
            "exception_type": _r27_exception_label(error),
            "source_code": _r27_safe_source_code(error, phase),
        },
    }
    sys.stdout.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
try:
    exec(compile("""
        + repr(body)
        + r""", "<r27-child-bootstrap>", "exec", dont_inherit=True), globals(), globals())
except SystemExit as error:
    if globals().get("_R27_EXPECTED_EXIT") is True:
        raise
    _r27_emit_entry_failure(error)
    raise SystemExit(2) from None
except BaseException as error:
    _r27_emit_entry_failure(error)
    raise SystemExit(2) from None
"""
    )
    return code


_CHILD_BOOTSTRAP = _wrap_child_bootstrap(_CHILD_BOOTSTRAP_BODY)


class SupervisorBlocked(RuntimeError):
    """Fixed source or process lifecycle gate failed closed."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise SupervisorBlocked(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _HASH_CHARS for ch in value)


def _activation_ready() -> bool:
    return (
        _r27_path_contract_ready()
        and ROOT_ACTUAL_ENABLED is True
        and ROOT_REVIEW_READY is True
        and ROOT_REVIEWED_ACTIVATION is True
        and ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED is True
        and ROOT_NATIVE_ENABLED is True
        and _valid_hash(ROOT_SELF_SHA256)
        and _valid_hash(ROOT_TEST_SHA256)
        and type(INERT_PUBLIC_PATH_COUNT) is int
        and INERT_PUBLIC_PATH_COUNT >= 0
        and type(ACTIVE_PUBLIC_PATH_COUNT) is int
        and ACTIVE_PUBLIC_PATH_COUNT >= INERT_PUBLIC_PATH_COUNT
        and ACTIVE_SOFTWARE_PATH_COUNT == 5
        and type(ACTIVE_PATH_ALIAS_COUNT) is int
        and ACTIVE_PATH_ALIAS_COUNT >= 0
        and set(ROOT_PACKET_PINS)
        == {"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json"}
        and set(ROOT_PACKET_AUX_PINS) == {"README.md", "qa/qa-summary.json"}
        and set(ROOT_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(v) for v in ROOT_PACKET_PINS.values())
        and all(_valid_hash(v) for v in ROOT_PACKET_AUX_PINS.values())
        and all(_valid_hash(v) for v in ROOT_REVIEW_PINS.values())
        and _valid_hash(R27_INVOKE_SHA256)
        and _valid_hash(R27_TEST_SHA256)
        and ROOT_TEST_SHA256 == R27_TEST_SHA256
        and set(R24_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        }
        and all(_valid_hash(v) for v in R24_PACKET_PINS.values())
        and set(R24_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(v) for v in R24_REVIEW_PINS.values())
        and set(R25_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        }
        and all(_valid_hash(v) for v in R25_PACKET_PINS.values())
        and set(R25_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(v) for v in R25_REVIEW_PINS.values())
        and _valid_hash(R19_TEST_SHA256)
        and set(R19_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        }
        and all(_valid_hash(v) for v in R19_PACKET_PINS.values())
        and set(R19_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(v) for v in R19_REVIEW_PINS.values())
        and _valid_hash(R19_DRIVER_SHA256)
        and _valid_hash(R19_BINDING_HELPER_SHA256)
        and _valid_hash(R19_WHOLE_SHA256)
        and R27_INVOKE_SOURCE == ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
        and R27_TEST
        == ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
        and R24_WHOLE_SOURCE
        == ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r24.py"
        and R24_TEST
        == ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r24_source_fake.py"
        and R24_PACKET
        == EVIDENCE
        / "iteration41-optional16-r33-whole-root-activation-r24-source-candidate-2026-10-08"
        and R24_REVIEW
        == EVIDENCE
        / "iteration41-optional16-r33-whole-root-activation-r24-independent-review-2026-10-08"
        and R19_DRIVER_SOURCE == ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
        and R19_TEST
        == ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r19_source_fake.py"
        and R19_PACKET
        == EVIDENCE
        / "iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
        and R19_REVIEW
        == EVIDENCE
        / "iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
        and ROOT_PACKET != R19_PACKET
        and ROOT_REVIEW != R19_REVIEW
        and ROOT_PACKET != R24_PACKET
        and ROOT_REVIEW != R24_REVIEW
        and ROOT_PACKET != R25_PACKET
        and ROOT_REVIEW != R25_REVIEW
        and ROOT_TEST_PATH != R19_TEST
        and ROOT_SELF_PATH != R24_WHOLE_SOURCE
        and ROOT_TEST_PATH != R24_TEST
        and R19_REVIEW_PINS["README.md"]
        == "7de172f561ebcc0ed51fee854e15bef47d20eca693b0f00390a23f3d16e6caf5"
    )


def _read_exact(path: Path, expected: str) -> bytes:
    _need(_valid_hash(expected), "source_pin_invalid")
    raw = path.read_bytes()
    _need(type(raw) is bytes and _sha(raw) == expected, "source_pin_mismatch")
    return raw


def _fixed_inputs() -> dict[Path, str]:
    _need(_valid_hash(ROOT_SELF_SHA256), "self_pin_unset")
    _need(_valid_hash(ROOT_TEST_SHA256), "test_pin_unset")
    _need(
        set(ROOT_PACKET_PINS)
        == {"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json"},
        "packet_pin_shape",
    )
    _need(
        set(ROOT_PACKET_AUX_PINS) == {"README.md", "qa/qa-summary.json"},
        "packet_aux_pin_shape",
    )
    _need(
        set(ROOT_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        },
        "review_pin_shape",
    )
    _need(
        set(R24_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        }
        and all(_valid_hash(value) for value in R24_PACKET_PINS.values()),
        "r24_packet_pin_shape",
    )
    _need(
        set(R24_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(value) for value in R24_REVIEW_PINS.values()),
        "r24_review_pin_shape",
    )
    _need(
        set(R25_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        }
        and all(_valid_hash(value) for value in R25_PACKET_PINS.values()),
        "r25_packet_pin_shape",
    )
    _need(
        set(R25_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        }
        and all(_valid_hash(value) for value in R25_REVIEW_PINS.values()),
        "r25_review_pin_shape",
    )
    _need(
        set(IMAGE_LEAF_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa-summary.json",
        },
        "image_packet_pin_shape",
    )
    # R25's HOLD review remains provenance. R19 remains the child aggregate.
    pins = {
        ROOT_SELF_PATH: ROOT_SELF_SHA256,
        ROOT_TEST_PATH: ROOT_TEST_SHA256,
        R27_INVOKE_SOURCE: R27_INVOKE_SHA256,
        R27_TEST: R27_TEST_SHA256,
        R19_TEST: R19_TEST_SHA256,
        R19_DRIVER_SOURCE: R19_DRIVER_SHA256,
        R19_BINDING_HELPER: R19_BINDING_HELPER_SHA256,
        R19_WHOLE_SOURCE: R19_WHOLE_SHA256,
        R24_WHOLE_SOURCE: R24_WHOLE_SHA256,
        R24_TEST: R24_TEST_SHA256,
        JOB_SOURCE: JOB_SOURCE_SHA256,
        IMAGE_LEAF_SOURCE: IMAGE_LEAF_SHA256,
        IMAGE_LEAF_TEST: IMAGE_LEAF_TEST_SHA256,
    }
    pins.update({ROOT_PACKET / name: digest for name, digest in ROOT_PACKET_PINS.items()})
    pins.update({ROOT_PACKET / name: digest for name, digest in ROOT_PACKET_AUX_PINS.items()})
    pins.update({ROOT_REVIEW / name: digest for name, digest in ROOT_REVIEW_PINS.items()})
    pins.update({R24_PACKET / name: digest for name, digest in R24_PACKET_PINS.items()})
    pins.update({R24_REVIEW / name: digest for name, digest in R24_REVIEW_PINS.items()})
    pins.update({R25_PACKET / name: digest for name, digest in R25_PACKET_PINS.items()})
    pins.update({R25_REVIEW / name: digest for name, digest in R25_REVIEW_PINS.items()})
    pins.update({R19_PACKET / name: digest for name, digest in R19_PACKET_PINS.items()})
    pins.update({R19_REVIEW / name: digest for name, digest in R19_REVIEW_PINS.items()})
    pins.update(
        {IMAGE_LEAF_PACKET / name: digest for name, digest in IMAGE_LEAF_PACKET_PINS.items()}
    )
    return pins


def _verify_pins(pins: dict[Path, str]) -> dict[Path, bytes]:
    _need(type(pins) is dict and 20 <= len(pins) <= 64, "fixed_pin_map_shape")
    result = {}
    for path, digest in sorted(pins.items(), key=lambda item: str(item[0]).casefold()):
        result[path] = _read_exact(path, digest)
    return result


def _load_exact(raw: bytes, path: Path, name: str) -> types.ModuleType:
    _need(type(raw) is bytes and type(name) is str and name not in sys.modules, "module_load_shape")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = __import__("importlib.machinery").machinery.ModuleSpec(
        name, loader=None, origin=str(path)
    )
    module.__verified_source_sha256__ = _sha(raw)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _strict_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


_CHILD_UNCERTAIN_REASONS = frozenset(
    {
        "root_adapter_exception",
        "source_scope_unavailable",
        "root_invocation_or_postverify_uncertain",
        "root_outer_exception",
    }
)
_CHILD_PHASES = frozenset(
    {
        "r2_invocation",
        "public_map_assembly",
        "reviewed_root_contract",
        "source_contract_validation",
        "source_custody_enter",
        "source_custody_entered",
        "current_image_check",
        "current_image_checked",
        "profiler_cache_verify",
        "profiler_cache_verified",
        "source_postverify_release",
        "source_released",
        "r5_driver_main",
        "r5_driver_returned",
    }
)
_CHILD_EXCEPTION_TYPES = frozenset(
    {
        "SystemExit",
        "RuntimeError",
        "OSError",
        "FileNotFoundError",
        "PermissionError",
        "TimeoutError",
        "ValueError",
        "TypeError",
        "KeyError",
        "UnicodeError",
        "AssertionError",
        "AttributeError",
        "EOFError",
        "ImportError",
        "NameError",
        "IndexError",
        "OverflowError",
        "ZeroDivisionError",
        "SystemError",
        "RootEnvelopeError",
        "BindingError",
        "_ParentDeadlineBlocked",
        "UNOBSERVED",
    }
)
_CHILD_CODE = re.compile(r"[a-z0-9_]{1,96}\Z")
_CHILD_PHASE_DIAGNOSTIC_SCHEMA = "iteration41.optional16.r33.root-invoke-r12.phase-diagnostic.v1"
_CHILD_APPLICATION_DIAGNOSTIC_SCHEMA = (
    "iteration41.optional16.r33.root-application-diagnostic.r12.v1"
)
_CHILD_APPLICATION_ERROR_CLASSES = frozenset(_CHILD_EXCEPTION_TYPES | {"NONE", "UNOBSERVED"})
_CHILD_DIAGNOSTIC_FIELDS = {
    "exception_diagnostic": "child_exception_diagnostic",
    "phase_diagnostic": "child_phase_diagnostic",
    "r2_application_diagnostic": "child_r2_application_diagnostic",
}


def _valid_child_exception_diagnostic(value: object) -> bool:
    if (
        type(value) is not dict
        or set(value) != {"phase", "exception_type", "source_code"}
        or type(value.get("phase")) is not str
        or value["phase"] not in (_CHILD_PHASES | set(_CHILD_ENTRY_PHASE_TO_CODE))
        or type(value.get("exception_type")) is not str
        or value["exception_type"] not in _CHILD_EXCEPTION_TYPES
    ):
        return False
    phase = value["phase"]
    source_code = value.get("source_code")
    if phase in _CHILD_ENTRY_PHASE_TO_CODE:
        if source_code == _CHILD_ENTRY_PHASE_TO_CODE[phase]:
            return True
        return (
            phase == "child_activation_binding"
            and value["exception_type"] == "RootEnvelopeError"
            and type(source_code) is str
            and source_code in _R27_BINDER_SAFE_CODES
        )
    if phase == "source_custody_entered":
        if source_code == "UNOBSERVED":
            return value["exception_type"] in _CHILD_EXCEPTION_TYPES
        return (
            value["exception_type"] == "RootEnvelopeError"
            and type(source_code) is str
            and source_code in _R27_SOURCE_CUSTODY_CODES
        )
    if source_code in _R27_SOURCE_CUSTODY_CODES:
        return False
    return source_code == "UNOBSERVED" or (
        type(source_code) is str and _CHILD_CODE.fullmatch(source_code) is not None
    )


def _valid_child_phase_diagnostic(value: object) -> bool:
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema",
            "availability",
            "phase",
            "transition_ordinal",
            "invocation_elapsed_ms",
            "phase_elapsed_ms",
        }
        or value.get("schema") != _CHILD_PHASE_DIAGNOSTIC_SCHEMA
    ):
        return False
    if value.get("availability") == "OBSERVED":
        return (
            type(value.get("phase")) is str
            and value["phase"] in _CHILD_PHASES
            and type(value.get("transition_ordinal")) is int
            and 0 <= value["transition_ordinal"] <= 64
            and all(
                type(value.get(key)) is int and 0 <= value[key] <= 120_000
                for key in ("invocation_elapsed_ms", "phase_elapsed_ms")
            )
            and value["phase_elapsed_ms"] <= value["invocation_elapsed_ms"]
        )
    return (
        value.get("availability") == "UNOBSERVED"
        and value.get("phase") == "UNOBSERVED"
        and value.get("transition_ordinal") is None
        and value.get("invocation_elapsed_ms") is None
        and value.get("phase_elapsed_ms") is None
    )


def _valid_child_application_diagnostic(value: object) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {
            "schema",
            "application_done_event_set",
            "application_thread_alive",
            "state_error_class",
            "stdout_overflow",
            "stderr_overflow",
            "stderr_nonempty",
            "application_elapsed_seconds",
        }
        and value.get("schema") == _CHILD_APPLICATION_DIAGNOSTIC_SCHEMA
        and all(
            value.get(key) is None or type(value.get(key)) is bool
            for key in (
                "application_done_event_set",
                "application_thread_alive",
                "stdout_overflow",
                "stderr_overflow",
                "stderr_nonempty",
            )
        )
        and type(value.get("state_error_class")) is str
        and value["state_error_class"] in _CHILD_APPLICATION_ERROR_CLASSES
        and value.get("application_elapsed_seconds") == "UNOBSERVED"
    )


def _parse_r12_frame(raw: bytes, return_code: object) -> dict[str, object]:
    _need(type(raw) is bytes and 0 < len(raw) <= CHILD_FRAME_LIMIT, "child_frame_size")
    _need(type(return_code) is int and return_code in (0, 2), "child_exit_code")
    _need(raw.endswith(b"\n") and raw.count(b"\n") == 1, "child_frame_delimiter")
    try:
        document = json.loads(raw[:-1].decode("utf-8", "strict"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise SupervisorBlocked("child_frame_invalid") from None
    _need(type(document) is dict, "child_frame_shape")
    _need(
        document.get("schema") == "iteration41.optional16.r33.root-invoke-r12.observation.v1",
        "child_frame_schema",
    )
    _need(
        document.get("status")
        in {"CLEAN_DRIVER_RESULT", "ROOT_UNCERTAIN_RETAINED_NO_PARSE", "BLOCKED"},
        "child_frame_status",
    )
    _need(
        type(document.get("strict_cases_passed")) is int and document["strict_cases_passed"] == 0,
        "child_frame_strict_count",
    )
    _need(document.get("case_pass") is False, "child_frame_case_pass")
    _need(document.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16", "child_frame_acceptance")
    if document["status"] == "CLEAN_DRIVER_RESULT":
        _need(
            type(document.get("root_exit_code")) is int
            and document["root_exit_code"] == return_code,
            "child_frame_exit_mismatch",
        )
        _need(document.get("complete_custody_postverified") is True, "child_frame_not_postverified")
        _need(
            document.get("native_cleanup_completed_before_outer_release") is True,
            "child_frame_cleanup_unverified",
        )
        _need(
            document.get("late_frame_parsed") is False
            and document.get("public_raw_saved") is False,
            "child_frame_capture_policy",
        )
    elif document["status"] == "ROOT_UNCERTAIN_RETAINED_NO_PARSE":
        required = {
            "schema",
            "status",
            "reason_code",
            "source_scope_released",
            "complete_custody_postverified",
            "source_custody_state",
            "source_scope_references_retained_until_root_process_exit",
            "complete_custody_retained_until_root_process_exit",
            "late_frame_parsed",
            "public_raw_saved",
            "strict_cases_passed",
            "case_pass",
            "acceptance",
        }
        optional_diagnostics = set(_CHILD_DIAGNOSTIC_FIELDS)
        _need(
            required <= set(document) <= required | optional_diagnostics,
            "child_uncertain_frame_fields",
        )
        reason_code = document.get("reason_code")
        _need(
            type(reason_code) is str and reason_code in _CHILD_UNCERTAIN_REASONS,
            "child_reason_code_invalid",
        )
        custody_state = document.get("source_custody_state")
        _need(
            type(custody_state) is str
            and custody_state in {"NOT_ESTABLISHED", "RELEASED", "UNOBSERVED", "HELD"},
            "child_custody_state_invalid",
        )
        _need(type(document.get("source_scope_released")) is bool, "child_scope_released_shape")
        _need(type(document.get("complete_custody_postverified")) is bool, "child_postverify_shape")
        _need(
            document["source_scope_released"] is (custody_state == "RELEASED")
            and document["complete_custody_retained_until_root_process_exit"]
            is (custody_state == "HELD"),
            "child_custody_state_mismatch",
        )
        _need(return_code == 2, "child_frame_uncertain_exit")
        _need(
            document.get("late_frame_parsed") is False
            and document.get("public_raw_saved") is False,
            "child_frame_uncertain_parse",
        )
        _need(
            document.get("source_scope_references_retained_until_root_process_exit") is True,
            "child_frame_uncertain_release",
        )
        for field, validator, code in (
            (
                "exception_diagnostic",
                _valid_child_exception_diagnostic,
                "child_exception_diagnostic_invalid",
            ),
            (
                "phase_diagnostic",
                _valid_child_phase_diagnostic,
                "child_phase_diagnostic_invalid",
            ),
            (
                "r2_application_diagnostic",
                _valid_child_application_diagnostic,
                "child_application_diagnostic_invalid",
            ),
        ):
            if field in document:
                _need(validator(document[field]), code)
        if "phase_diagnostic" in document:
            application = document.get("r2_application_diagnostic")
            _need(
                type(application) is dict
                and application.get("application_done_event_set") is False
                and application.get("application_thread_alive") is True,
                "child_phase_diagnostic_without_live_application",
            )
    else:
        _need(
            return_code == 2 and document.get("root_actual_enabled") is False,
            "child_frame_blocked_exit",
        )
    result = {
        "status": document["status"],
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
    }
    if document["status"] == "ROOT_UNCERTAIN_RETAINED_NO_PARSE":
        result["child_reason_code"] = document["reason_code"]
        for source_field, output_field in _CHILD_DIAGNOSTIC_FIELDS.items():
            if source_field in document:
                result[output_field] = dict(document[source_field])
    return result


class _Reader:
    def __init__(self, stream: object):
        self.stream = stream
        self.data = bytearray()
        self.eof = False
        self.overflow = False
        self.error = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            while True:
                chunk = self.stream.read(4096)
                if chunk == b"":
                    self.eof = True
                    return
                if type(chunk) is not bytes:
                    self.error = True
                    return
                room = max(0, STREAM_LIMIT - len(self.data))
                if len(chunk) > room:
                    self.overflow = True
                if room:
                    self.data.extend(chunk[:room])
        except BaseException:
            self.error = True


def _writer(stream: object, payload: bytes, state: dict[str, object]) -> None:
    try:
        stream.write(payload)
        stream.flush()
        stream.close()
        state["done"] = True
    except BaseException:
        state["error"] = True


def _activation_payload(parent_deadline: float) -> bytes:
    now = time.monotonic()
    _need(
        _r27_path_contract_ready()
        and sys.platform == "win32"
        and sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 5)
        and type(now) is float
        and type(parent_deadline) is float
        and math.isfinite(now)
        and math.isfinite(parent_deadline)
        and 0.0 < parent_deadline - now <= WHOLE_CALL_SECONDS,
        "parent_deadline_invalid",
    )
    document = {
        "schema": "iteration41.optional16.r33.whole-call.r27-child-activation.v1",
        "invoke": {
            "path": str(R27_INVOKE_SOURCE),
            "sha256": R27_INVOKE_SHA256,
            "test_path": str(R27_TEST),
            "test_sha256": R27_TEST_SHA256,
            "packet_dir": str(R19_PACKET),
            "packet_pins": dict(R19_PACKET_PINS),
            "review_dir": str(R19_REVIEW),
            "review_pins": dict(R19_REVIEW_PINS),
            "review_readme_sha256": R19_REVIEW_PINS["README.md"],
        },
        "driver": {
            "path": str(R19_DRIVER_SOURCE),
            "sha256": R19_DRIVER_SHA256,
            "test_path": str(R19_TEST),
            "test_sha256": R19_TEST_SHA256,
            "packet_dir": str(R19_PACKET),
            "packet_pins": dict(R19_PACKET_PINS),
            "review_dir": str(R19_REVIEW),
            "review_pins": dict(R19_REVIEW_PINS),
            "review_readme_sha256": R19_REVIEW_PINS["README.md"],
            "active_path": str(R27_DRIVER_ACTIVE_PATH),
        },
        "counts": {
            "inert_public_paths": INERT_PUBLIC_PATH_COUNT,
            "active_public_paths": ACTIVE_PUBLIC_PATH_COUNT,
            "software_paths": ACTIVE_SOFTWARE_PATH_COUNT,
            "path_aliases": ACTIVE_PATH_ALIAS_COUNT,
        },
        "fresh_paths": dict(R27_FRESH_PATHS),
        "parent_deadline_monotonic": parent_deadline,
        "parent_deadline_domain": PARENT_DEADLINE_CLOCK_DOMAIN,
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    _need(len(raw) <= PAYLOAD_LIMIT, "activation_payload_too_large")
    return raw


def _child_command() -> list[str]:
    return [FIXED_EXECUTABLE, "-I", "-S", "-B", "-c", _CHILD_BOOTSTRAP]


def _new_native(job_module: types.ModuleType):
    return job_module._WinJobNative()


def _observe_image(image_module: types.ModuleType, process: object):
    return image_module.observe_suspended_child_image(process)


def _valid_image_observation(value: object, pid: object) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {
            "schema",
            "child_pid",
            "fixed_executable_path_observed",
            "active_at_observation",
            "suspension_verified",
            "job_assignment_verified",
            "physical_image_custody_verified",
            "whole_command_g1",
            "strict_cases_passed",
            "authority",
        }
        and value.get("schema") == "iteration41.suspended-child-image-observation.v2"
        and type(pid) is int
        and value.get("child_pid") == pid
        and value.get("fixed_executable_path_observed") is True
        and value.get("active_at_observation") is True
        and value.get("suspension_verified") is False
        and value.get("job_assignment_verified") is False
        and value.get("physical_image_custody_verified") is False
        and value.get("whole_command_g1") is False
        and type(value.get("strict_cases_passed")) is int
        and value.get("strict_cases_passed") == 0
        and value.get("authority") is False
    )


def _clock() -> float:
    return time.monotonic()


def _close_stream(stream: object, thread: threading.Thread, deadline: float) -> bool:
    while thread.is_alive() and _clock() < deadline:
        thread.join(min(POLL_SECONDS, max(0.0, deadline - _clock())))
    if thread.is_alive():
        return False
    try:
        if not getattr(stream, "closed", False):
            stream.close()
        return bool(getattr(stream, "closed", True))
    except BaseException:
        return False


def _retain(context: dict[str, object]) -> None:
    if context not in _RETAINED:
        _RETAINED.append(context)


def _safe_observation(
    status: str,
    reason: str,
    *,
    child_status: str | None = None,
    child_reason_code: str | None = None,
    child_exception_diagnostic: dict[str, object] | None = None,
    child_phase_diagnostic: dict[str, object] | None = None,
    child_r2_application_diagnostic: dict[str, object] | None = None,
) -> dict[str, object]:
    result = {
        "schema": "iteration41.optional16.r33.whole-call-supervisor.r27.v1",
        "status": status,
        "reason_code": reason,
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "provider_session_created": False,
        "network_access_allowed": False,
        "whole_command_g1": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
    }
    if child_status is not None:
        result["child_status"] = child_status
    if child_reason_code is not None:
        result["child_reason_code"] = child_reason_code
    if child_exception_diagnostic is not None:
        result["child_exception_diagnostic"] = dict(child_exception_diagnostic)
    if child_phase_diagnostic is not None:
        result["child_phase_diagnostic"] = dict(child_phase_diagnostic)
    if child_r2_application_diagnostic is not None:
        result["child_r2_application_diagnostic"] = dict(child_r2_application_diagnostic)
    return result


def _run_fixed_call(
    started: float,
    deadline: float,
    payload: bytes,
    job_module: types.ModuleType,
    image_module: types.ModuleType,
    native: object,
) -> tuple[int, dict[str, object]]:
    """Run the fixed R12 child through injected low-level fakes in source tests."""
    context: dict[str, object] = {"job": None, "process": None, "native": native}
    process = None
    job_handle = None
    stdout_reader = stderr_reader = None
    input_state: dict[str, object] = {"done": False, "error": False}
    input_thread = None
    return_code = 2
    reason = "outer_start_failed"
    child_status = None
    child_projection: dict[str, object] = {}
    clean = False
    deadline_expired = False
    cleanup_deadline = None
    try:
        _need(_clock() < deadline, "outer_deadline_before_job")
        job_handle = native.create_job()
        _need(job_handle is not None, "outer_job_create")
        context["job"] = job_handle
        _need(_clock() < deadline, "outer_deadline_before_popen")
        flags = (
            0x4
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        process = subprocess.Popen(
            _child_command(),
            cwd=str(ROOT),
            env=job_module._minimal_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            shell=False,
            creationflags=flags,
        )
        context["process"] = process
        _need(
            process is not None and type(process.pid) is int and process.pid > 0,
            "outer_process_invalid",
        )
        stdout_reader = _Reader(process.stdout)
        stderr_reader = _Reader(process.stderr)
        stdout_reader.thread.start()
        stderr_reader.thread.start()
        _need(_clock() < deadline, "outer_deadline_before_assign")
        native.assign(job_handle, process)
        context["job_assigned"] = True
        observation = _observe_image(image_module, process)
        _need(_valid_image_observation(observation, process.pid), "outer_image_observation_invalid")
        context["image_observed"] = True
        _need(_clock() < deadline, "outer_deadline_before_resume")
        native.resume_initial_thread(process.pid)
        context["resumed"] = True
        input_thread = threading.Thread(
            target=_writer, args=(process.stdin, payload, input_state), daemon=True
        )
        input_thread.start()
        context["input_thread"] = input_thread
        while _clock() < deadline:
            remaining = deadline - _clock()
            if remaining <= 0:
                break
            try:
                return_code = process.wait(timeout=min(POLL_SECONDS, remaining))
                context["process_reaped"] = True
                break
            except subprocess.TimeoutExpired:
                continue
        if not context.get("process_reaped"):
            deadline_expired = True
            reason = "outer_call_deadline"
        else:
            if _clock() >= deadline:
                deadline_expired = True
                reason = "outer_completion_at_or_after_deadline"
            else:
                cleanup_deadline = min(
                    started + WHOLE_CALL_SECONDS + CLEANUP_SECONDS, _clock() + CLEANUP_SECONDS
                )
                context["cleanup_deadline"] = cleanup_deadline
                reason = "outer_lifecycle_incomplete"
                while _clock() < cleanup_deadline:
                    active = native.active_processes(job_handle)
                    if type(active) is not int or active < 0:
                        reason = "outer_job_count_invalid"
                        break
                    if _clock() >= cleanup_deadline:
                        deadline_expired = True
                        reason = "outer_job_query_at_or_after_cleanup_deadline"
                        break
                    if active == 0:
                        context["job_empty"] = True
                        break
                    time.sleep(min(POLL_SECONDS, max(0.0, cleanup_deadline - _clock())))
                if context.get("job_empty") and _clock() < cleanup_deadline:
                    if input_thread.is_alive():
                        reason = "outer_input_writer_incomplete"
                    elif input_state.get("error") is True or input_state.get("done") is not True:
                        reason = "outer_input_writer_failed"
                    else:
                        for reader in (stdout_reader, stderr_reader):
                            while reader.thread.is_alive() and _clock() < cleanup_deadline:
                                reader.thread.join(
                                    min(POLL_SECONDS, max(0.0, cleanup_deadline - _clock()))
                                )
                        if any(
                            reader.thread.is_alive() for reader in (stdout_reader, stderr_reader)
                        ):
                            reason = "outer_reader_incomplete"
                        elif not all(
                            reader.eof and not reader.error and not reader.overflow
                            for reader in (stdout_reader, stderr_reader)
                        ):
                            reason = "outer_capture_incomplete"
                        elif stderr_reader.data:
                            reason = "outer_stderr_not_empty"
                        elif _clock() >= cleanup_deadline:
                            deadline_expired = True
                            reason = "outer_capture_at_or_after_cleanup_deadline"
                        else:
                            reason = "outer_stream_close_failed"
                            input_closed = _close_stream(
                                process.stdin, input_thread, cleanup_deadline
                            )
                            stdout_closed = _close_stream(
                                process.stdout, stdout_reader.thread, cleanup_deadline
                            )
                            stderr_closed = _close_stream(
                                process.stderr, stderr_reader.thread, cleanup_deadline
                            )
                            if input_closed and stdout_closed and stderr_closed:
                                reason = "outer_job_close_failed"
                                native.close(job_handle)
                                context["job_closed"] = True
                                reason = "outer_sources_postverify_failed"
                                _verify_pins(_fixed_inputs())
                                context["source_postverified"] = True
                                if _clock() < cleanup_deadline:
                                    parsed = _parse_r12_frame(
                                        bytes(stdout_reader.data), return_code
                                    )
                                    context["child_status"] = parsed["status"]
                                    context["child_projection"] = {
                                        key: value
                                        for key, value in parsed.items()
                                        if key.startswith("child_")
                                    }
                                    child_status = parsed["status"]
                                    child_projection = dict(context["child_projection"])
                                    clean = True
                                    reason = "none"
                else:
                    if _clock() >= deadline:
                        deadline_expired = True
                        reason = "outer_call_deadline"
    except BaseException as error:
        reason = (
            error.args[0] if type(error) is SupervisorBlocked and error.args else "outer_exception"
        )
        if type(reason) is not str or not reason.replace("_", "").isalnum() or len(reason) > 80:
            reason = "outer_exception"
    finally:
        if not clean:
            if cleanup_deadline is None:
                cleanup_deadline = min(
                    started + WHOLE_CALL_SECONDS + CLEANUP_SECONDS, _clock() + CLEANUP_SECONDS
                )
            context["cleanup_started"] = True
            if job_handle is not None and context.get("job_closed") is not True:
                try:
                    native.terminate(job_handle)
                except BaseException:
                    context["terminate_failed"] = True
            if process is not None:
                try:
                    if process.poll() is None and (
                        context.get("job_assigned") is not True
                        or context.get("terminate_failed") is True
                    ):
                        process.kill()
                except BaseException:
                    context["kill_failed"] = True
                try:
                    remaining = max(0.0, cleanup_deadline - _clock())
                    process.wait(timeout=remaining)
                    context["process_reaped"] = True
                except BaseException:
                    context["reap_failed"] = True
            if job_handle is not None and context.get("job_closed") is not True:
                try:
                    active = native.active_processes(job_handle)
                    context["job_empty"] = type(active) is int and active == 0
                except BaseException:
                    context["job_query_failed"] = True
            for reader in (stdout_reader, stderr_reader):
                if reader is not None:
                    while reader.thread.is_alive() and _clock() < cleanup_deadline:
                        reader.thread.join(min(POLL_SECONDS, max(0.0, cleanup_deadline - _clock())))
            if input_thread is not None and input_thread.is_alive():
                while input_thread.is_alive() and _clock() < cleanup_deadline:
                    input_thread.join(min(POLL_SECONDS, max(0.0, cleanup_deadline - _clock())))
            threads_stopped = all(
                thread is None or not thread.is_alive()
                for thread in (
                    input_thread,
                    stdout_reader.thread if stdout_reader else None,
                    stderr_reader.thread if stderr_reader else None,
                )
            )
            if process is not None and threads_stopped:
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        if stream is not None and not getattr(stream, "closed", False):
                            stream.close()
                    except BaseException:
                        context["stream_close_failed"] = True
            if (
                job_handle is not None
                and context.get("job_empty") is True
                and context.get("job_closed") is not True
            ):
                try:
                    native.close(job_handle)
                    context["job_closed"] = True
                except BaseException:
                    context["job_close_failed"] = True
            context["cleanup_deadline_met"] = _clock() < cleanup_deadline
            _retain(context)
    if clean:
        return_code = int(return_code)
        return return_code, _safe_observation(
            "CHILD_RETURNED", "none", child_status=child_status, **child_projection
        )
    # The source map is deliberately retained even when cleanup appears complete.
    context["deadline_expired"] = deadline_expired
    return 2, _safe_observation("ROOT_UNCERTAIN_RETAINED_NO_PARSE", reason)


def _create_once_claim() -> None:
    _need(ROOT_CONTROL.is_dir(), "outer_control_missing")
    raw = b"iteration41-optional16-r33-whole-call-once-r21\n"
    try:
        with ROOT_ONCE_PATH.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise SupervisorBlocked("outer_once_already_consumed") from None
    _need(ROOT_ONCE_PATH.read_bytes() == raw, "outer_once_readback_failed")


def _actual_run() -> tuple[int, dict[str, object]]:
    started = _clock()
    _need(
        sys.platform == "win32"
        and sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 5)
        and type(started) is float
        and math.isfinite(started),
        "parent_deadline_clock_domain_unsupported",
    )
    deadline = started + WHOLE_CALL_SECONDS
    pins = _fixed_inputs()
    _verify_pins(pins)
    payload = _activation_payload(deadline)
    _create_once_claim()
    job_module = _load_exact(
        _read_exact(JOB_SOURCE, JOB_SOURCE_SHA256),
        JOB_SOURCE,
        "_iteration41_optional16_r33_whole_call_job_r1",
    )
    image_module = _load_exact(
        _read_exact(IMAGE_LEAF_SOURCE, IMAGE_LEAF_SHA256),
        IMAGE_LEAF_SOURCE,
        "_iteration41_optional16_r33_whole_call_image_r2",
    )
    _need(image_module.ROOT_NATIVE_ENABLED is False, "image_leaf_disk_default_open")
    image_module.ROOT_NATIVE_ENABLED = True
    _need(_clock() < deadline, "outer_prelaunch_deadline")
    native = _new_native(job_module)
    return _run_fixed_call(started, deadline, payload, job_module, image_module, native)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--execute-r33-root-r5"]):
        return _emit(_safe_observation("BLOCKED", "arguments_rejected"), 2)
    if not _activation_ready():
        return _emit(_safe_observation("PREPARED_UNSET", "root_activation_unset"), 2)
    try:
        return_code, observation = _actual_run()
    except BaseException as error:
        reason = (
            error.args[0]
            if type(error) is SupervisorBlocked and error.args
            else "outer_preflight_failed"
        )
        if type(reason) is not str or not reason.replace("_", "").isalnum() or len(reason) > 80:
            reason = "outer_preflight_failed"
        return _emit(_safe_observation("BLOCKED", reason), 2)
    return _emit(observation, return_code)


def _emit(document: dict[str, object], exit_code: int) -> int:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
