"""Code-owned artifact and endpoint checks for the private CTP read path.

The installed-root import boundary proves where ``bt_api_*`` came from.  It
does not identify which wheel was installed or whether its files still match
that wheel.  This module adds that missing check before the CTP composition
root reads credentials.

The reviewed base/CTP pair below is scoped to the registered SimNow sandbox
read-only preflight. Managed writes additionally require a separately pinned
``bt_api_py`` parent distribution, which is not yet approved. A pin binds both
the PEP 610 wheel digest and the exact installed ``RECORD``; the latter is
checked against every listed file. This is local artifact identity evidence,
not a publisher signature or a general SDK release approval.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import importlib
import importlib.util
import importlib.metadata
import io
import json
import marshal
import os
import re
import stat
import sysconfig
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import CodeType, MappingProxyType
from typing import Mapping, Sequence, Tuple
from urllib.parse import unquote, urlsplit


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIST_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Legacy profile-compatibility table, checked on 2026-09-23 against the SimNow
# product page: https://www.simnow.com.cn/product.action . The config-front-
# pair path uses verify_ctp_sdk_artifact_provenance_for_fronts instead and does
# not select or allow-list endpoints through this table.
_ALLOWED_SIMNOW_PROFILE_FRONTS = MappingProxyType(
    {
        "set1_group1": (
            "tcp://180.168.146.187:10201",
            "tcp://180.168.146.187:10211",
        ),
        "set1_group2": (
            "tcp://180.168.146.187:10202",
            "tcp://180.168.146.187:10212",
        ),
        "set2_7x24": (
            "tcp://180.168.146.187:10130",
            "tcp://180.168.146.187:10131",
        ),
    }
)


class CtpArtifactProvenanceError(ValueError):
    """Redacted fail-closed artifact or SimNow profile rejection."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("the installed CTP SDK artifact or profile was rejected")


def _reject(reason: str) -> None:
    raise CtpArtifactProvenanceError(reason)


@dataclass(frozen=True)
class CtpSdkArtifactPin:
    """One code-reviewed wheel identity and its installed-file manifest."""

    distribution: str
    module: str
    version: str
    wheel_filename: str
    wheel_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.distribution) is not str
            or not _DIST_NAME_RE.fullmatch(self.distribution)
            or type(self.module) is not str
            or not re.fullmatch(r"bt_api_[a-z0-9_]+", self.module)
            or type(self.version) is not str
            or not self.version
            or type(self.wheel_filename) is not str
            or not self.wheel_filename.endswith(".whl")
            or Path(self.wheel_filename).name != self.wheel_filename
            or type(self.wheel_sha256) is not str
            or not _SHA256_RE.fullmatch(self.wheel_sha256)
            or type(self.record_sha256) is not str
            or not _SHA256_RE.fullmatch(self.record_sha256)
        ):
            raise ValueError("invalid CTP SDK artifact pin")


# Candidate I2 is pinned only for the registered SimNow sandbox read-only
# preflight. Its clean source commits are base 73e860e2 and CTP 28157ce3;
# the CTP wheel carries H2's bounded native shutdown receipt and scoped query
# certificate, plus fixed, value-free MD login callback diagnostics. A present
# but blank rate ExchangeID remains unverified; a missing field rejects.
# The parent distribution is
# deliberately absent: managed SimNow requires all three modules and remains
# closed. These local wheel identities do not approve a general SDK release
# or a production route.
# Runtime configuration and caller input cannot add or replace pins.
CTP_SDK_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
            record_sha256="47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i2",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl",
            wheel_sha256="988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff",
            record_sha256="4953ef5cb13468a300693fd3c37b7eb59c4afd0727e3d6dbcf8a15de5abebe08",
        ),
    }
)

# The I3 one-shot MD diagnostic candidate is pinned in its own table so its
# experimental wheel cannot silently replace the accepted I2 identity.  The
# wheel was built from clean source SHA ce3127ade8cef00f02b9a6cee6545fb147cda8b9.
# This SDK wheel contains trading APIs; these hashes establish artifact
# identity only.  Read-only behavior remains a property of the diagnostic
# caller's constrained call chain, not of the artifact itself.  This pin is
# not registered and must not be used for managed execution or general SDK
# acceptance.
CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CTP_SDK_ARTIFACT_PINS["bt_api_base"],
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i3",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i3-cp311-cp311-win_amd64.whl",
            wheel_sha256="c1ead607c9b6758b7850b8517996cc1654514cdd8fa81ef10fbf2858e1d914d8",
            record_sha256="df7644d667a1adeff151c98e58f788e2637cf77473b7cf37f6928cfffda17cb8",
        ),
    }
)

# The I4 one-shot MD diagnostic is an independent, unregistered candidate
# built from clean CTP source commit 809239fdc0b7982d3512f4289e3e8dbcbd43a523.
# Its base wheel bytes and CTP wheel remain the reviewed I2/I4 artifacts. The
# separately pinned base RECORD hash captures I4's audited no-bytecode install
# and leaves the I2 registered-route pin untouched. These identities grant no
# execution or general provider authority.
CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
            record_sha256="aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i4",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i4-cp311-cp311-win_amd64.whl",
            wheel_sha256="96f8c874871b6f571e3abb14bf25b32a4ccb133ca09e51767584e5c03682283e",
            record_sha256="327998c95de9c3a69ac9cb40444361822c8602e30975067705a750c782ffbd6f",
        ),
    }
)

# The unregistered I5 MD-only diagnostic is built from clean CTP source commit
# a101590f5f29070439c13b6062b3487abee936cc. Its BrokerID response-shape
# classification is value-free metadata and does not change login acceptance.
# The base wheel and its installed RECORD match the separately reviewed I4
# install. This table is diagnostic-only and grants no write or live route.
CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"],
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i5",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i5-cp311-cp311-win_amd64.whl",
            wheel_sha256="552dc8711523aef930864b7441a2a93ed2f4cb9541acc15435ac8fe9a3ca98dc",
            record_sha256="3320042e1b0d4706cda2c9272806c91aa5ef7efe329f85178db45f3ed2b36026",
        ),
    }
)

# The unregistered I6 MD-only diagnostic is built from clean CTP source commit
# d85cd1571000c63d38bb9417a4942ec2692c5ad6. Its response-field shapes
# are value-free metadata and do not change login acceptance. This independent
# pin grants no managed write or live authority.
CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"],
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i6",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i6-cp311-cp311-win_amd64.whl",
            wheel_sha256="3788bf75019eb8fa685b828be9dae66b2f17d41422e770441870a105e02c1ded",
            record_sha256="e5ab9889853f1d01683c2754156ca4c2875cad2ceafdea05baadf5d2420a9bb6",
        ),
    }
)

# The unregistered I7 MD-only diagnostic adds the native callback storage
# shape enums. Its artifact identity is independent of the earlier diagnostic
# wheels and grants no write or live authority.
CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"],
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i7",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i7-cp311-cp311-win_amd64.whl",
            wheel_sha256="22bc34140233785abcad61e7c3bc4dbb85c9d97b171692d5e6b44cf89eda94b4",
            record_sha256="03b4d23a6a647c4b29c392304e56dcd3be8b776e9c3eef695af0adcfbbdc45b6",
        ),
    }
)

# The unregistered I8 MD diagnostic pins this retained wheel pair. The I8 CTP
# wheel is reported as built from source commit
# a7d9b04d5520373d80ed395f76d2939ca5206e4b with MSVC /Brepro and a fixed
# SOURCE_DATE_EPOCH. Same-path separated-time builds were reported identical;
# independent reproducibility review is pending. The RECORD pins below are
# hashes of the audited installed distributions (the verifier checks those
# files), not the RECORD entries embedded in the wheel archives. These hashes
# establish artifact identity only and do not register the diagnostic, approve
# a provider session, or grant write capability.
CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="2f413f7e914c4bbd1dcd47b3b95a3fb36e224dda2c4db97bdda35bf61797ad68",
            record_sha256="40052081b6ddff201e059818d310e83c012f7e428ba2e76dc64af0417e68de4d",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i8",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i8-cp311-cp311-win_amd64.whl",
            wheel_sha256="f354327f092993cce7954339deca3b5cc32ab953f5fd330ba5a6b3a7ea94f715",
            record_sha256="1b2ce3ad778712e735d9e76f44e81748c8af323ece5bc0a0e96e51148882c48a",
        ),
    }
)

# Historical I9 source/build evidence only. Two clean-clone builds reproduced
# this wheel and its embedded RECORD, but the installed RECORD differs by
# pip-generated direct_url.json: targets A/B hash to 1021d0... and 0866e6....
# CtpSdkArtifactPin.record_sha256 is checked against the installed RECORD, so
# the embedded hash is not a valid installed pin and neither target-specific
# hash is a portable pin. Keep the diagnostic table empty so its verifier fails
# closed until an exact installation scope is deliberately reviewed.
CTP_I9_REPRODUCED_WHEEL_SHA256 = "aa094c039788a41adf975cfeee839fa3baf1bcef3878ae53d10eefb44410a4a3"
CTP_I9_EMBEDDED_WHEEL_RECORD_SHA256 = (
    "d030ccf23d59a5f77230b490df52aa48c4cbecd67b2a78b7e782600126565841"
)
CTP_I9_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET: Mapping[str, str] = MappingProxyType(
    {
        "a": "1021d0edf7e4aa1f19b86dd5b0140634b19b589773e0aa7b55153c438367d466",
        "b": "0866e6150a881f0eb227fa80dfc215fbab65bb3b6f216be6b10d12c354226089",
    }
)
CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType({})

# I10 was built from clean source commit a6253a58b1ebca11f58c8836fbed757d0daf7582;
# two clean-clone wheel builds matched byte-for-byte, including this embedded
# RECORD. pip's installed RECORD also covers direct_url.json, so it depends on
# the local wheel source path: the two reproduction installs yielded distinct
# installed RECORD hashes. Keep those reproduction hashes as inert evidence;
# the verifier pin below uses the installed RECORD from the controlled
# no-index/no-deps CPython 3.11 venv installed from reproduction wheel A. This
# diagnostic table is independent of the registered I2 and fail-closed I9
# tables. I10 contains native CTP/trading APIs and its artifact identity grants
# no provider session, write, or general SDK-release authority.
CTP_I10_REPRODUCED_WHEEL_SHA256 = "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
CTP_I10_EMBEDDED_WHEEL_RECORD_SHA256 = (
    "0f7f5724ed45f98a491f8f6bcc767f9825551a8e0753f0911a40e993a9c23911"
)
CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET: Mapping[str, str] = MappingProxyType(
    {
        "a": "c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673",
        "b": "cb768050b6f1a15c300591f3eae51e1ed9b4a7301a311817f88b285d85c40be2",
    }
)
CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
            record_sha256="47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i10",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i10-cp311-cp311-win_amd64.whl",
            wheel_sha256=CTP_I10_REPRODUCED_WHEEL_SHA256,
            record_sha256=CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET["a"],
        ),
    }
)

# Independent code-owned pin for the unregistered I12 TD-only read-only
# candidate. The wheel bytes and controlled install source are the same as
# I10, but the MD-only pin above does not authorize or verify this TD call
# path. Keep a separate installed-RECORD pin and verifier so either diagnostic
# can be reviewed, changed, or closed without inheriting the other's scope.
# These are the exact base/CTP installed records from the fixed I10 isolated
# CPython 3.11 environment; the CTP record includes its pip direct_url.json.
CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
            record_sha256="47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i10",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i10-cp311-cp311-win_amd64.whl",
            wheel_sha256="e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4",
            record_sha256="c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673",
        ),
    }
)

# Candidate-private I13 MD diagnostic pin. This is tied to the isolated
# CPython 3.11.5 I13 venv whose direct_url and installed RECORD were audited
# alongside the two-clone wheel receipt. The base RECORD differs from the I10
# environment because this installation came from its own retained base wheel
# path. These identities are diagnostic-only and grant no provider or write
# authority.
CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.5",
            wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
            wheel_sha256="2f413f7e914c4bbd1dcd47b3b95a3fb36e224dda2c4db97bdda35bf61797ad68",
            record_sha256="6f73003cdba8f15468faa0264eb99c81578e6648c00ebf5de4c7161c676f7113",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.3+iteration41.i13",
            wheel_filename="bt_api_ctp-2.0.3+iteration41.i13-cp311-cp311-win_amd64.whl",
            wheel_sha256="c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d",
            record_sha256="d21876f577927651a585ad7273c5bdcf508d65766f2a05e2f5a06c8a29798217",
        ),
    }
)

_READONLY_CTP_MODULES = ("bt_api_base", "bt_api_ctp")
_MANAGED_SIMNOW_MODULES = (*_READONLY_CTP_MODULES, "bt_api_py")


def _distribution_key(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def _is_link_or_reparse(result: os.stat_result) -> bool:
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(result, "st_file_attributes", 0)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_point)


def _regular_file(path: Path) -> bytes:
    try:
        result = os.lstat(str(path))
    except OSError:
        _reject("artifact_file_unavailable")
    if _is_link_or_reparse(result) or not stat.S_ISREG(result.st_mode):
        _reject("artifact_file_invalid")
    try:
        return path.read_bytes()
    except OSError:
        _reject("artifact_file_unavailable")
    raise AssertionError("unreachable")


def _concrete_directory(path: Path) -> Path:
    try:
        result = os.lstat(str(path))
    except OSError:
        _reject("artifact_install_root_invalid")
    if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
        _reject("artifact_install_root_invalid")
    try:
        physical = path.resolve(strict=True)
    except (OSError, RuntimeError):
        _reject("artifact_install_root_invalid")
    if os.path.normcase(str(path.absolute())) != os.path.normcase(str(physical)):
        _reject("artifact_install_root_invalid")
    return physical


def _interpreter_install_roots() -> Tuple[Path, ...]:
    try:
        reported = sysconfig.get_paths()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        _reject("artifact_install_root_invalid")
    roots = []
    for key in ("purelib", "platlib"):
        value = reported.get(key)
        if not isinstance(value, (str, os.PathLike)) or not str(value):
            continue
        root = _concrete_directory(Path(value))
        if all(os.path.normcase(str(root)) != os.path.normcase(str(item)) for item in roots):
            roots.append(root)
    if not roots:
        _reject("artifact_install_root_invalid")
    return tuple(roots)


def _relative_record_path(value: str) -> Tuple[str, ...]:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        _reject("artifact_record_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
    ):
        _reject("artifact_record_invalid")
    return tuple(path.parts)


def _file_digest_matches(path: Path, expected: str, expected_size: str) -> None:
    if not expected.startswith("sha256="):
        _reject("artifact_record_invalid")
    digest_text = expected[len("sha256=") :]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
    if not digest_text or any(character not in alphabet for character in digest_text):
        _reject("artifact_record_invalid")
    try:
        padding = "=" * ((4 - len(digest_text) % 4) % 4)
        expected_digest = base64.urlsafe_b64decode(digest_text + padding)
    except (ValueError, binascii.Error):
        _reject("artifact_record_invalid")
    if len(expected_digest) != hashlib.sha256().digest_size:
        _reject("artifact_record_invalid")
    if not expected_size or not expected_size.isdecimal():
        _reject("artifact_record_invalid")
    contents = _regular_file(path)
    if len(contents) != int(expected_size) or hashlib.sha256(contents).digest() != expected_digest:
        _reject("artifact_file_hash_mismatch")


def _same_code(left: CodeType, right: CodeType) -> bool:
    """Compare executable code fields while ignoring only trace-position tables."""

    fields = (
        "co_argcount",
        "co_posonlyargcount",
        "co_kwonlyargcount",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_names",
        "co_varnames",
        "co_freevars",
        "co_cellvars",
        "co_filename",
        "co_firstlineno",
        "co_exceptiontable",
    )
    if any(getattr(left, field, None) != getattr(right, field, None) for field in fields):
        return False
    if len(left.co_consts) != len(right.co_consts):
        return False
    for left_value, right_value in zip(left.co_consts, right.co_consts):
        if isinstance(left_value, CodeType) or isinstance(right_value, CodeType):
            if not isinstance(left_value, CodeType) or not isinstance(right_value, CodeType):
                return False
            if not _same_code(left_value, right_value):
                return False
        elif type(left_value) is not type(right_value) or left_value != right_value:
            return False
    return True


def _validate_pyc_cache(
    path: Path, package_root: Path, install_root: Path, recorded: set[str]
) -> None:
    """Accept only bytecode whose executable code is derived from pinned source."""

    if path.parent.name != "__pycache__" or path.suffix != ".pyc":
        _reject("artifact_bytecode_invalid")
    try:
        source_path = Path(importlib.util.source_from_cache(str(path)))
        source_relative = source_path.relative_to(install_root).as_posix()
        source_path.relative_to(package_root)
    except (NotImplementedError, OSError, ValueError):
        _reject("artifact_bytecode_invalid")
    if source_relative not in recorded:
        _reject("artifact_bytecode_invalid")
    source_bytes = _regular_file(source_path)
    pyc_bytes = _regular_file(path)
    if len(pyc_bytes) < 16 or pyc_bytes[:4] != importlib.util.MAGIC_NUMBER:
        _reject("artifact_bytecode_invalid")

    flags = int.from_bytes(pyc_bytes[4:8], "little")
    if flags & ~3:
        _reject("artifact_bytecode_invalid")
    if flags & 1:
        if pyc_bytes[8:16] != importlib.util.source_hash(source_bytes):
            _reject("artifact_bytecode_invalid")
    else:
        try:
            source_stat = os.stat(str(source_path))
        except OSError:
            _reject("artifact_bytecode_invalid")
        timestamp = int(source_stat.st_mtime) & 0xFFFFFFFF
        source_size = source_stat.st_size & 0xFFFFFFFF
        if (
            int.from_bytes(pyc_bytes[8:12], "little") != timestamp
            or int.from_bytes(pyc_bytes[12:16], "little") != source_size
        ):
            _reject("artifact_bytecode_invalid")

    try:
        cached_code = marshal.loads(pyc_bytes[16:])
    except (EOFError, ValueError, TypeError):
        _reject("artifact_bytecode_invalid")
    if not isinstance(cached_code, CodeType):
        _reject("artifact_bytecode_invalid")
    optimisation_match = re.search(r"\.opt-([12])$", path.stem)
    optimisation = int(optimisation_match.group(1)) if optimisation_match else 0
    try:
        source_code = compile(
            source_bytes,
            cached_code.co_filename,
            "exec",
            dont_inherit=True,
            optimize=optimisation,
        )
    except (SyntaxError, TypeError, ValueError):
        _reject("artifact_bytecode_invalid")
    if not _same_code(cached_code, source_code):
        _reject("artifact_bytecode_invalid")


def _record_relative_path(files: Sequence[object]) -> str:
    candidates = []
    for item in files:
        value = str(item)
        if value.endswith(".dist-info/RECORD"):
            candidates.append(value)
    if len(candidates) != 1:
        _reject("artifact_record_invalid")
    return candidates[0]


def _validate_package_inventory(package_root: Path, install_root: Path, recorded: set[str]) -> None:
    for directory, child_directories, filenames in os.walk(str(package_root), followlinks=False):
        current = Path(directory)
        kept_directories = []
        for name in child_directories:
            child = current / name
            try:
                result = os.lstat(str(child))
            except OSError:
                _reject("artifact_file_invalid")
            if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
                _reject("artifact_file_invalid")
            kept_directories.append(name)
        child_directories[:] = kept_directories
        for name in filenames:
            path = current / name
            if name.endswith(".pyc"):
                _validate_pyc_cache(path, package_root, install_root, recorded)
                continue
            if current.name == "__pycache__":
                _reject("artifact_bytecode_invalid")
            try:
                result = os.lstat(str(path))
            except OSError:
                _reject("artifact_file_invalid")
            if _is_link_or_reparse(result) or not stat.S_ISREG(result.st_mode):
                _reject("artifact_file_invalid")
            try:
                relative = path.relative_to(install_root).as_posix()
            except ValueError:
                _reject("artifact_install_root_invalid")
            if relative not in recorded:
                _reject("artifact_record_mismatch")


def _validate_installed_distribution(pin: CtpSdkArtifactPin) -> Path:
    try:
        distribution = importlib.metadata.distribution(pin.distribution)
    except importlib.metadata.PackageNotFoundError:
        _reject("artifact_unavailable")
    except Exception:
        _reject("artifact_metadata_invalid")

    metadata = getattr(distribution, "metadata", None)
    name = metadata.get("Name") if metadata is not None else None
    version = metadata.get("Version") if metadata is not None else None
    if (
        type(name) is not str
        or _distribution_key(name) != _distribution_key(pin.distribution)
        or type(version) is not str
        or version != pin.version
    ):
        _reject("artifact_identity_mismatch")

    try:
        install_root = _concrete_directory(Path(distribution.locate_file("")))
        allowed_roots = _interpreter_install_roots()
    except CtpArtifactProvenanceError:
        raise
    except Exception:
        _reject("artifact_install_root_invalid")
    if all(
        os.path.normcase(str(install_root)) != os.path.normcase(str(allowed))
        for allowed in allowed_roots
    ):
        _reject("artifact_install_root_invalid")

    files = getattr(distribution, "files", None)
    if not files:
        _reject("artifact_record_invalid")
    try:
        file_entries = tuple(files)
    except (TypeError, ValueError):
        _reject("artifact_record_invalid")
    record_relative = _record_relative_path(file_entries)
    record_parts = _relative_record_path(record_relative)
    record_path = install_root.joinpath(*record_parts)
    record_bytes = _regular_file(record_path)
    if hashlib.sha256(record_bytes).hexdigest() != pin.record_sha256:
        _reject("artifact_record_pin_mismatch")
    try:
        record_text = record_bytes.decode("utf-8")
        rows = tuple(csv.reader(io.StringIO(record_text, newline="")))
    except (UnicodeDecodeError, csv.Error):
        _reject("artifact_record_invalid")
    if not rows:
        _reject("artifact_record_invalid")

    recorded = set()
    pyc_entries = []
    record_self_rows = 0
    for row in rows:
        if len(row) != 3:
            _reject("artifact_record_invalid")
        relative = row[0]
        parts = _relative_record_path(relative)
        if relative in recorded:
            _reject("artifact_record_invalid")
        recorded.add(relative)
        path = install_root.joinpath(*parts)
        if relative == record_relative:
            record_self_rows += 1
            if row[1] or row[2]:
                _reject("artifact_record_invalid")
            continue
        if path.suffix == ".pyc":
            if row[1] or row[2]:
                _file_digest_matches(path, row[1], row[2])
            elif "__pycache__" in parts:
                pyc_entries.append(path)
            else:
                _reject("artifact_record_invalid")
            continue
        _file_digest_matches(path, row[1], row[2])
    distribution_paths = {str(item) for item in file_entries}
    if record_self_rows != 1 or recorded != distribution_paths:
        _reject("artifact_record_mismatch")

    package_root = _concrete_directory(install_root / pin.module)
    for path in pyc_entries:
        _validate_pyc_cache(path, package_root, install_root, recorded)
    _validate_package_inventory(package_root, install_root, recorded)

    try:
        direct_url_text = distribution.read_text("direct_url.json")
        direct_url = json.loads(direct_url_text) if direct_url_text is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _reject("artifact_provenance_invalid")
    if type(direct_url) is not dict or "dir_info" in direct_url:
        _reject("artifact_provenance_invalid")
    archive_info = direct_url.get("archive_info")
    url = direct_url.get("url")
    if type(archive_info) is not dict or type(url) is not str:
        _reject("artifact_provenance_invalid")
    archive_hash = archive_info.get("hash")
    archive_hashes = archive_info.get("hashes")
    if archive_hash is not None and archive_hash != "sha256=" + pin.wheel_sha256:
        _reject("artifact_wheel_hash_mismatch")
    if archive_hashes is not None and archive_hashes != {"sha256": pin.wheel_sha256}:
        _reject("artifact_wheel_hash_mismatch")
    if archive_hash is None and archive_hashes is None:
        _reject("artifact_provenance_invalid")
    try:
        parsed_url = urlsplit(url)
        wheel_name = PurePosixPath(unquote(parsed_url.path)).name
    except (TypeError, ValueError):
        _reject("artifact_provenance_invalid")
    if (
        parsed_url.scheme != "file"
        or parsed_url.netloc not in ("", "localhost")
        or parsed_url.query
        or parsed_url.fragment
        or wheel_name != pin.wheel_filename
    ):
        _reject("artifact_provenance_invalid")
    return package_root


def _verify_package_import_root(module_name: str, package_root: Path) -> None:
    """Require Python's resolved package path to be the pinned installation."""

    try:
        spec = importlib.util.find_spec(module_name)
        origin = getattr(spec, "origin", None)
        locations = getattr(spec, "submodule_search_locations", None)
        if type(origin) is not str or locations is None:
            _reject("artifact_import_rejected")
        resolved_origin = Path(origin).resolve(strict=True)
        expected_init = (package_root / "__init__.py").resolve(strict=True)
        resolved_locations = tuple(Path(location).resolve(strict=True) for location in locations)
    except CtpArtifactProvenanceError:
        raise
    except Exception:
        _reject("artifact_import_rejected")
    if resolved_origin != expected_init or resolved_locations != (
        package_root.resolve(strict=True),
    ):
        _reject("artifact_import_rejected")


def _verified_official_fronts(profile: str, package_root: Path) -> Tuple[str, str]:
    try:
        module = importlib.import_module("bt_api_ctp.ctp_env_selector")
    except Exception:
        _reject("artifact_import_rejected")
    module_file = getattr(module, "__file__", None)
    if type(module_file) is not str:
        _reject("artifact_import_rejected")
    expected_module_file = package_root / "ctp_env_selector.py"
    try:
        if Path(module_file).resolve(strict=True) != expected_module_file.resolve(strict=True):
            _reject("artifact_import_rejected")
    except (OSError, RuntimeError):
        _reject("artifact_import_rejected")
    official_fronts = getattr(module, "official_simnow_fronts", None)
    code = getattr(official_fronts, "__code__", None)
    code_filename = getattr(code, "co_filename", None)
    if not callable(official_fronts) or type(code_filename) is not str:
        _reject("artifact_import_rejected")
    try:
        if Path(code_filename).resolve(strict=True) != expected_module_file.resolve(strict=True):
            _reject("artifact_import_rejected")
        value = official_fronts(profile)
    except CtpArtifactProvenanceError:
        raise
    except Exception:
        _reject("profile_front_mismatch")
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not str
        or type(value[1]) is not str
    ):
        _reject("profile_front_mismatch")
    return value


def simnow_profile_for_fronts(*, td_front: str, md_front: str) -> str:
    """Return the reviewed SDK profile for one exact TD/MD front pair.

    Runtime config may carry the official front strings directly, but it may
    not introduce an endpoint, mix the TD front from one profile with the MD
    front from another, or rely on URL parser normalization.  The returned
    profile is code-derived metadata for SDK policy only; callers should keep
    and pass the original configured strings to any provider API that accepts
    them.
    """

    try:
        _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    except CtpArtifactProvenanceError as error:
        if error.reason == "front_pair_syntax_invalid":
            _reject("profile_front_mismatch")
        raise
    for profile, (reviewed_td_front, reviewed_md_front) in _ALLOWED_SIMNOW_PROFILE_FRONTS.items():
        if td_front == reviewed_td_front and md_front == reviewed_md_front:
            return profile
    _reject("profile_front_mismatch")
    raise AssertionError("unreachable")


def _validate_exact_tcp_front_pair(*, td_front: str, md_front: str) -> Tuple[str, str]:
    """Validate canonical CTP TCP front strings without selecting a profile."""

    if type(td_front) is not str or type(md_front) is not str:
        _reject("front_pair_syntax_invalid")
    if any(
        not value
        or value != value.strip()
        or len(value) > 128
        or any(character.isspace() or ord(character) < 0x20 for character in value)
        for value in (td_front, md_front)
    ):
        _reject("front_pair_syntax_invalid")
    for value in (td_front, md_front):
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            _reject("front_pair_syntax_invalid")
        if (
            parsed.scheme != "tcp"
            or not parsed.hostname
            or port is None
            or not 1 <= port <= 65535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or value != "tcp://{0}:{1}".format(parsed.hostname, port)
        ):
            _reject("front_pair_syntax_invalid")
    return td_front, md_front


def simnow_fronts_for_profile(profile: str) -> Tuple[str, str]:
    """Return the code-owned TD/MD pair for a reviewed SDK profile."""

    if type(profile) is not str or profile not in _ALLOWED_SIMNOW_PROFILE_FRONTS:
        _reject("profile_not_pinned")
    return _ALLOWED_SIMNOW_PROFILE_FRONTS[profile]


def _verify_pinned_sdk_distributions(
    required_modules: Sequence[str],
    *,
    pins: Mapping[str, CtpSdkArtifactPin],
) -> Mapping[str, Path]:
    """Validate each required pinned distribution, RECORD, and import root."""

    package_roots = {}
    for module_name in required_modules:
        pin = pins.get(module_name)
        if (
            type(pin) is not CtpSdkArtifactPin
            or pin.module != module_name
            or _distribution_key(pin.distribution) != module_name
        ):
            _reject("artifact_pin_unavailable")
        package_roots[module_name] = _validate_installed_distribution(pin)
    for module_name, package_root in package_roots.items():
        _verify_package_import_root(module_name, package_root)
    return package_roots


def verify_ctp_sdk_artifact_provenance_for_fronts(*, td_front: str, md_front: str) -> None:
    """Verify pinned SDK artifacts for an already selected, explicit CTP pair.

    The caller must validate its configuration seal before passing these
    strings. This function requires canonical TCP syntax and verifies the
    installed distributions, but it does not select a SimNow profile or
    require static address allowlist membership. The exact input strings are
    never rewritten or returned as normalized endpoint values.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(_READONLY_CTP_MODULES, pins=CTP_SDK_ARTIFACT_PINS)


def verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the isolated I3 one-shot diagnostic's exact base and CTP wheels.

    The configured pair is checked for canonical TCP syntax only; no endpoint
    is selected or allow-listed here. This opt-in verifier is for an
    unregistered diagnostic call chain. The pinned CTP wheel includes trading
    APIs, so this check does not make the artifact read-only or authorize any
    provider action.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the exact I2 base and I4 CTP wheels for the unregistered probe.

    Only canonical endpoint syntax and installed artifact identity are
    checked. This call selects no endpoint and confers no provider authority.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the isolated I5 SDK wheel pair for one explicit configured pair.

    This unregistered, read-only diagnostic gate checks syntax and installed
    artifact identity only. It does not select an endpoint or authorize writes.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i6_oneshot_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the isolated I6 SDK wheel pair for one configured read-only probe.

    This unregistered diagnostic gate checks exact endpoint syntax and installed
    artifact identity only; it neither selects an endpoint nor authorizes writes.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Fail closed until I7's exact diagnostic wheel identities are reviewed."""

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the retained installed I8 wheel pair for one exact front."""

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i9_oneshot_md_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Fail closed because I9 currently has source/build evidence, not an installed pin."""

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the exact I10 wheel pair for one explicit, unregistered MD diagnostic.

    This gate checks canonical endpoint syntax and installed artifact identity
    only. The CTP artifact includes trading APIs; verification neither selects
    a provider endpoint nor authorizes a session or write.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the separately reviewed installed artifacts for I12's TD path.

    This checks exact wheel and installed-RECORD identity only. TD-only scope
    comes from the caller's reviewed call graph and session contract; artifact
    identity grants no provider session, settlement, or write authority.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS,
    )


def verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify the isolated I13 base/CTP wheels for its unregistered MD probe."""

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES,
        pins=CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
    )


def verify_ctp_simnow_managed_artifact_provenance_for_fronts(
    *, td_front: str, md_front: str
) -> None:
    """Verify exact wheel provenance for managed SimNow's three SDK packages.

    The managed CTP write contract imports authorization and credential-binding
    types from the separate ``bt_api_py`` distribution. Keep the read-only
    verifier independent of that package, and require all three reviewed wheels
    before a managed caller extracts credentials or imports/constructs an SDK
    client.
    """

    _validate_exact_tcp_front_pair(td_front=td_front, md_front=md_front)
    _verify_pinned_sdk_distributions(_MANAGED_SIMNOW_MODULES, pins=CTP_SDK_ARTIFACT_PINS)


def verify_ctp_sdk_artifact_provenance(sdk_profile: str) -> None:
    """Verify SDK pins and the package's exact code-owned SimNow front map.

    This compatibility API remains profile-bound. New explicit-front
    compositions should use verify_ctp_sdk_artifact_provenance_for_fronts.
    """

    if type(sdk_profile) is not str or sdk_profile not in _ALLOWED_SIMNOW_PROFILE_FRONTS:
        _reject("profile_not_pinned")
    package_roots = _verify_pinned_sdk_distributions(
        _READONLY_CTP_MODULES, pins=CTP_SDK_ARTIFACT_PINS
    )

    actual_fronts = _verified_official_fronts(sdk_profile, package_roots["bt_api_ctp"])
    if actual_fronts != _ALLOWED_SIMNOW_PROFILE_FRONTS[sdk_profile]:
        _reject("profile_front_mismatch")


__all__ = [
    "CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I9_EMBEDDED_WHEEL_RECORD_SHA256",
    "CTP_I9_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET",
    "CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I9_REPRODUCED_WHEEL_SHA256",
    "CTP_I10_EMBEDDED_WHEEL_RECORD_SHA256",
    "CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET",
    "CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_I10_REPRODUCED_WHEEL_SHA256",
    "CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS",
    "CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS",
    "CTP_SDK_ARTIFACT_PINS",
    "CtpArtifactProvenanceError",
    "CtpSdkArtifactPin",
    "simnow_fronts_for_profile",
    "simnow_profile_for_fronts",
    "verify_ctp_simnow_managed_artifact_provenance_for_fronts",
    "verify_ctp_sdk_artifact_provenance",
    "verify_ctp_sdk_artifact_provenance_for_fronts",
    "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i6_oneshot_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i9_oneshot_md_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts",
    "verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts",
    "verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts",
]
