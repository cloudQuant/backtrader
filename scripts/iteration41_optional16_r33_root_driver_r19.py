"""Closed R19 successor candidate for the Optional16 R33 local diagnostic.

This source is closed by default. A separately reviewed R15 root entry must
hold the public source/runtime closure, bind a same-host monotonic parent
deadline, and fill activation fields in memory. The local diagnostic does not
establish provider, account, case, or registry acceptance.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import io
import json
import math
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import zipfile

ROOT = Path(r"D:\source_code\backtrader")
E = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
DRIVER_PACKET = E / "iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
DRIVER_REVIEW = E / "iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
CONTROL = Path(r"D:\temp\iteration41-optional16-r33-root-control-r19")
SCRATCH = Path(r"D:\temp\iteration41-optional16-r33-matrix-scratch-r19")
ROOT_DRIVER_PATH = Path(r"D:\temp\iteration41-optional16-r33-root-driver-r19.py")
PROGRESS_NAME = "r33-r19-progress.frames"
PROGRESS_PATH = CONTROL / PROGRESS_NAME
PROGRESS_HEADER_PREFIX = b"R5SIDECAR|"
PROGRESS_PENDING = PROGRESS_HEADER_PREFIX + b"PENDING_\n"
PROGRESS_OPENED = PROGRESS_HEADER_PREFIX + b"OPENED__\n"
PROGRESS_COMPLETE = PROGRESS_HEADER_PREFIX + b"COMPLETE\n"
PROGRESS_FAILED = PROGRESS_HEADER_PREFIX + b"FAILED__\n"
_TRACE_START_FAILURE_FRAME = b"R26DIAG|matrix_trace_start|FAILED\n"
PROGRESS_FOOTERLESS_LIMIT = 8192 + (64 * 1024) + len(_TRACE_START_FAILURE_FRAME)
PROGRESS_MAX_BYTES = len(PROGRESS_PENDING) + PROGRESS_FOOTERLESS_LIMIT
R2_PREDECESSOR_PACKET = E / "iteration41-optional16-r32-root-driver-r2-source-fake-2026-10-05"
R2_PREDECESSOR_PACKET_PINS = {
    "source-bundle.zip": "57f723b9f1fa48af605898a7436b9aad6a850e6e6a002b6e663269f76dc124fc",
    "source-index.json": "2c6045ac035fe69ea9abd41a0f8e7dfafa902b3888e098fedb0dde4461531ffc",
    "source-pins.json": "df940a0031ce1d7fc0321d1ce7bb1def166d3849ee85836a3fa08f505285f4d9",
    "checkpoint.json": "0edfb0b440f44ba2d5b6e7da8105000596eadd77f53089be0d3cd2e1b278b457",
    "README.md": "d3e5901611b62ba6c318b27ddaf8164d283acfccacd2dfe00363ee4dab1a9a73",
    "qa/qa-summary.json": "fd04d4a83d6aee32f3427fdc04a1cae430f9516bb301a54a90b23f066e5d30cc",
}
R2_PREDECESSOR_REVIEW = (
    E / "iteration41-optional16-r32-root-driver-r2-independent-review-r1-2026-10-05"
)
R2_PREDECESSOR_REVIEW_PINS = {
    "review.json": "da438051cc2ced2c4267b88fdb521103253f24af704b9ae4604b2ac133188778",
    "review-bundle.zip": "4d8c492dab6b576812e5e655643caed01e493784e9d89c245064a997fc30e8e9",
    "review-index.json": "d86e6a77f9e7aa043c12f91452a838bea008a451876bb0fd4cd2eda3b6a14640",
    "review-checkpoint.json": "344d0e76c864ccfb6eae07dcc3a7a265703680442ba2eea327ebc9fd28026bff",
    "README.md": "6eb29ed6c4dc65979426b462f5d28b2fcba22e1c786cab5c9e57746ba3b696de",
    "qa-summary.json": "0f9039da6f8898c62d98c6c6bcc082c62a7c48b1890d20cb7b3199be42f17cde",
    "source-pins.json": "65bd38c482e30d84f9c0c2025cd27abd510de1e41d64f5dcd0fd66b292ff19cf",
}
R1_DRIVER = ROOT / "scripts/iteration41_optional16_r32_matrix_root_driver_r1.py"
R1_DRIVER_SHA256 = "238a179459357ca7f21998cb2f2684f4b5ef1209efc521e14d4a0e2868e5eaaa"
R1_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r1.py"
R1_TEST_SHA256 = "dd2850a575ab745295fb3011886a0ab0bedfdfd4be8870cfd312c5276888a4d7"
R1_PACKET = E / "iteration41-optional16-r32-root-driver-r1-source-fake-2026-10-04"
R1_PACKET_PINS = {
    "source-bundle.zip": "991363bfafb740933cf2ad32cbbf450d8e51d8792e6d0d350d530db206f3d897",
    "source-index.json": "8c7f094a92f9b72887a2067c9edd45961e1426ddc4a8ff97bb4485a21832aac3",
    "source-pins.json": "81e2fac9bb796bc95695477a4f07f53270538c947df597bbe58fe6f3edef2bd3",
    "checkpoint.json": "90861972ff145aacb5eca648b4165163117aa64879d099072d550248b8157ad2",
    "README.md": "0a3842ebce28ea45cca068d8e73087c25ecf51af378ce14eca22adb9151eb8af",
}
R1_REVIEW = E / "iteration41-optional16-r32-root-driver-r1-independent-review-r1-2026-10-04"
R1_REVIEW_PINS = {
    "review.json": "99cf611e10b15c63fc501da6b54104e9a6fc1840bec31ab717606c5987c21d21",
    "review-bundle.zip": "95dc04ad61d4898e4ce1e185482233f2cc8a744c4893f5c86004d5909762600d",
    "review-index.json": "f24b550190279c554fd1a341041dc75bb7019884a6f166717c83291def72fbc7",
    "review-checkpoint.json": "ad3df4c21bcac56d64ef01737745e65fc49596865db45dd9cb12d3cc016842a4",
    "README.md": "2ddb427b8ace00a9450bc4f3d21a956f06c3dc16232b6679301c2235826d1b3c",
}
R1_PACKET_MEMBER_PINS = {
    "README.md": "0a3842ebce28ea45cca068d8e73087c25ecf51af378ce14eca22adb9151eb8af",
    "qa/qa-summary.json": "5649af644a8ab2a701bc408f8abc11990e738dea6d3c3ca509ab8072eee065e4",
    "scripts/iteration41_optional16_r32_matrix_root_driver_r1.py": R1_DRIVER_SHA256,
    "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r1.py": R1_TEST_SHA256,
}
ROOT_PUBLIC_PINS = E / "iter41-zmq-r6-map-r3-20261007/source/p/r25-public-path-pins.json"
ROOT_PUBLIC_PINS_SHA256 = "5264b763bac6aac5d70fcbaa4e7cea423544ce90cd367e5e34da55c1680b9899"
ROOT_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r19_binding.py"
ROOT_BINDING_HELPER_SHA256 = "1774b2776c9c03c0e10574fda4f58093f3c2947d902d78c2d41bac9d4c47ba58"
DRIVER_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r19_source_fake.py"

R16_PACKET = E / "iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07"
R16_PACKET_PINS = {
    "source-bundle.zip": "b68d48374b2fe88d21a633a24f4da58e932c441189f0c86465a241487aa60184",
    "source-index.json": "423074c1f0123cde9612e74bf5dec34ecdb000bd2bc90b41346def853ee56066",
    "source-pins.json": "b1a80e804f44e19adc0cbef555ee50c81a920853de6b6fe75e2bfea249e5d3a0",
    "checkpoint.json": "20ec128fb84436de65b1446c59df7727cf67e300c5667f02dff34e4e399aa1e1",
    "README.md": "7277e16543e7afdbf344d4228baa5510c62815a8d146ae009fd645712a9dc713",
    "qa/qa-summary.json": "247c17c2a55ed4be129d6655ed81fa0889595844bc2ad296cd0f77b6e678f513",
}
R16_REVIEW = E / "iteration41-optional16-r33-deadline-r15-successor-independent-review-2026-10-07"
R16_REVIEW_PINS = {
    "review.json": "ad9ac104f313e4dddd0b975426697d2e290da972cd2c6ce6e2db7407f4b71d02",
    "review-bundle.zip": "bd0d9d319ebe8471a281a9670966a8aab11846f3698d54e57cec50e8c30021ca",
    "review-index.json": "820d87fca9d37ff97014375957aba052a5120de9e0375c365c8f533faf4661a4",
    "review-checkpoint.json": "8658685567370080ffd847415adbbd0c0672692f21e905ea87794303f1c6b0aa",
    "README.md": "2ec949a02051a7d934df7c903f2123931397a489c61170b33c07f29b1e713afb",
}
R17_PACKET = E / "iteration41-optional16-r33-whole-root-activation-r17-source-candidate-2026-10-07"
R17_PACKET_PINS = {
    "source-bundle.zip": "54719e0ff6137eb19f1d114fa921dd51acad7bbb12217ec81d433b43e39ae61f",
    "source-index.json": "57ff1f5d4480f455444d5b1c827a3d9d4876fe2bb5b3d4492e52d040f171a903",
    "source-pins.json": "f7c1ee066a537b79e0cadd35527dd9614eeb860ff3be276245608b1346634b18",
    "checkpoint.json": "53e1cfe0b42650aa768a1b84812bf4eaa3d65992722839fbdd760ccdf092d6c1",
    "README.md": "7458c71d822ac2bc2f9e1d95c907e533ece5cf3d5b9ca6262f9fe242f462ec05",
    "qa/qa-summary.json": "c9c13a0867c6445c46eed19e59d89959ce58a3ef0c4677296adf4846991f9ceb",
}
R17_REVIEW = E / "iteration41-optional16-r33-whole-root-activation-r17-independent-review-2026-10-07"
R17_REVIEW_PINS = {
    "review.json": "0731c95d7dcf5447a33aad952a466fa5bfcceed09287ede4a44a38ae0202b4f5",
    "review-bundle.zip": "0c81b9f5534650586bc00ba46c29ad4d5c141d6c0933e3e72e313d5bacfccda8",
    "review-index.json": "7f75adc01c0867da93062137fbd8cc54e25c22caebd00f5a5ddcc018bb14a0e4",
    "review-checkpoint.json": "d361d19c2cd2f3b918bc49feced6bf0b402fe1b71fe3c4093732b10107466c69",
    "README.md": "defe2616d4cfa044c7545e91bba04193d360ed591e72b9ebd05a561c54116e5e",
}
R18_PACKET = E / "iteration41-optional16-r33-whole-root-activation-r18-source-candidate-2026-10-07"
R18_PACKET_PINS = {
    "source-bundle.zip": "3e14e06b18b71c5345daefd13b19e6ee1f0bbe4a9148c64ebcd567e3f9b36d1a",
    "source-index.json": "4053337d27345ae5501facdfdefb6b969e3655f37710f7f24ba38d76915a7597",
    "source-pins.json": "940f5773e88c97d618e719418cddbcc59eb7454262e1d5b9b707cedc6fe637c2",
    "checkpoint.json": "3026cc634d27dbe90a24be379c5cb5674ad2c65081b438b2ae4ae9f399309aed",
    "README.md": "a5efef43fcf39c654192a646304c5c24db12c5ee7a356affaa73116a8158d3d9",
    "qa/qa-summary.json": "d3352334f0650b6df66ba5e1594c067d83a64a88c2d272e22e3795c234bfdfa3",
}
R18_REVIEW = E / "iteration41-optional16-r33-whole-root-activation-r18-independent-review-2026-10-07"
R18_REVIEW_PINS = {
    "review.json": "3185fad5fe8b3d5844980f0ea5052f69b6e81df2e99b0afa42505e03a6607dae",
    "review-bundle.zip": "29715403363bffe1dbfa3d8ba82afb53d152804a8679dbbe6c5cfd2babe7dc2b",
    "review-index.json": "61bc04e464973aae698764ffa8467471748da55e4f606b803f4549c35b4ff401",
    "review-checkpoint.json": "30e7b4d28982e903cdd7827ddb2af6289e42b2ddd2d494c59ae498afba09d995",
    "README.md": "7984f515ce30f76e79d80f7b74dffd8e1bbd854fd58148a482629f3f2382547e",
}
R18_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r18_binding.py"
R18_HELPER_SHA256 = "5977009ff0d6bfafb98f5e9eace3e49cd9e49a15c760237ff5cee4d0f9c2fb43"
R18_ROLE_PATHS = {
    "binding_helper": "scripts/iteration41_optional16_r33_deadline_r18_binding.py",
    "driver": "scripts/iteration41_optional16_r33_root_driver_r18.py",
    "invoke": "scripts/iteration41_optional16_r33_root_held_invoke_r18.py",
    "whole_call_supervisor": "scripts/iteration41_optional16_r33_whole_call_supervisor_r18.py",
}
R18_TEST_PATH = "tests/unit/scripts/test_iteration41_optional16_r33_activation_r18_source_fake.py"
_R15_PACKET_REL = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r33-deadline-propagation-r15-source-fake-2026-10-07"
_R15_REVIEW_REL = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r33-deadline-propagation-r15-independent-review-r1-2026-10-07"
_PRIOR_R2_OBSERVATION_REL = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r33-whole-call-r2-root-tool-observation-2026-10-06/observation.json"
_R15_PUBLIC_EVIDENCE_PINS = {
    f"{_R15_PACKET_REL}/source-bundle.zip": "ef4b95d618e503da9f99346a0bb44b2c54595ba87df8dcc8617782037402e044",
    f"{_R15_PACKET_REL}/source-index.json": "99b31e4759fffb22c7d64057e287f3b553611343e0b36712671abde57c1deab5",
    f"{_R15_PACKET_REL}/source-pins.json": "d6001eb1f00307b9b407bc784c993c77f357c95646ff2192ccf0f22f176d97ad",
    f"{_R15_PACKET_REL}/checkpoint.json": "d6867f7558706d39f59ae0c31e3dc342a4e20436d41c11e849909454f3c3aab0",
    f"{_R15_PACKET_REL}/README.md": "332191d9744303dad91e986c8a49d8d135f471bfbef6411e735e9b02fdb2a70f",
    f"{_R15_REVIEW_REL}/review.json": "db173e605489a9271260a758ad7864cba5ae722bb3537183c444e95eed3a93b2",
    f"{_R15_REVIEW_REL}/review-bundle.zip": "8e24bbda889b44fc7de7e8faee154ad201193b8517a9b7567567960a0a5b2f69",
    f"{_R15_REVIEW_REL}/review-index.json": "b1b5591b71c6ea107d18f30318b9e6928ba574ae0aa735e5c5edb6062438b3b5",
    f"{_R15_REVIEW_REL}/review-checkpoint.json": "dd1e1456593aa2706967283801a9dcb131ac5607fc5e604e9875b5423356a5e1",
    f"{_R15_REVIEW_REL}/README.md": "a6657a1355f1ed0bb4baa9496e19488859d53492ff548c74cb8d2680760ff5b7",
    _PRIOR_R2_OBSERVATION_REL: "d9b286e1c5191c582c69f612d2a460dc16ea11a56f9a66cc88f6f4ad73e257ab",
    "scripts/iteration41_optional16_r33_whole_call_supervisor_r15.py": "6e4256ca5e6007d2df009d788881ec269bdd026a7a7b7c3b3331a876651c7906",
    "scripts/iteration41_optional16_r33_root_held_invoke_r15.py": "aa62711f9ca72f27d89e1cd6d58a1fc7757ab6dc34eb96b0d0f086c0a1d736b3",
    "scripts/iteration41_optional16_r33_root_held_glue_r15.py": "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98",
    "scripts/iteration41_optional16_r33_root_driver_r15.py": "d4ce983d2db52833c82d1dc089b504dcec0996cf12c6165b4a5679e493c7a94d",
    "tests/unit/scripts/test_iteration41_optional16_r33_deadline_r15.py": "bc79d68d7dfb0fa0bde15df28087d0745880b702c90ba30bb3f50f0d10df40b8",
}

R31_PACKET = E / "iteration41-optional16-r31-guard-profile-source-fake-r1-2026-10-04"
R31_PACKET_PINS = {
    "source-bundle.zip": "2d737e7cd04991ac69a3ef1b1d9496c6b2425ccfaba2d2c41219a6a43a57957c",
    "source-index.json": "827b344b59b85da245564c2d799bf4e40e064c0570992153ad381a12db006db1",
    "source-pins.json": "b5f6114047b378fcaabcfdcb2eff8f4fe520fe751838b0edc49b10ec071449aa",
    "checkpoint.json": "a54b7224a638c4c551416131f3fb936182884129fdb568a9632568a0cbfe33b2",
    "profile.json": "7ded196bf717a300fa2be38e847b71f6019d88b7c7712690722457554d8ba2ff",
    "README.md": "a51f41b03692c0a94119a5ddff0f8d368499e73bd54ff8e74d9863ce077faa6a",
    "qa/qa-summary.json": "5a9c4e6b12d4d91c815442710b7735c7ce58b8399c643d396f64907b1a8c5aec",
}
R31_CANDIDATE = ROOT / "backtrader_runtime/certification_optional16_guard_profile_r31_candidate.py"
R31_CANDIDATE_SHA256 = "e33409aec7409121913566bf97ac8c99aeb28f2d0938dff52187626e270e5977"
R31_MATRIX = ROOT / "backtrader_runtime/certification_optional16_installed_matrix_r30.py"
R31_MATRIX_SHA256 = "c1232a57dec7515c7f832c952382effb0c0d78c581fe962ded45836c16f6da3f"
R31_OWNER = ROOT / "backtrader_runtime/certification_optional_owner_integration_r30_candidate.py"
R31_OWNER_SHA256 = "549658ff93dd2c24a57883a873963d2a7bde5f6f521cc06a4ef53821b4a9f838"
R31_PROFILE_MODULE = (
    R31_PACKET / "candidate/certification_optional16_guard_profile_r31_candidate.py"
)
R31_PROFILE_MODULE_SHA256 = R31_CANDIDATE_SHA256
R31_TEST = (
    ROOT / "tests/unit/runtime/test_certification_optional16_guard_profile_r31_source_fake.py"
)
R31_TEST_SHA256 = "7c60074f2395199287983e13df50b5a2c82644d27297c7ea5f0f8f70927f1f2a"
R31_ACTIVE_SOURCES = {
    "backtrader_runtime/certification_optional16_guard_profile_r31_candidate.py": R31_CANDIDATE_SHA256,
    "backtrader_runtime/certification_optional16_installed_matrix_r30.py": R31_MATRIX_SHA256,
    "backtrader_runtime/certification_optional_owner_integration_r30_candidate.py": R31_OWNER_SHA256,
    "backtrader_runtime/certification_optional_admission_policy.py": "3b14896dbdaf90296d539a2ec274aa548e5455a06e4762aa996be13cbdbcaf5c",
    "backtrader_runtime/certification_optional_topology.py": "c47f7ac68e225c6b5b6da5d42f0e1b80c208812501e108c3a97d9d3157e546f5",
    "profile.json": "7ded196bf717a300fa2be38e847b71f6019d88b7c7712690722457554d8ba2ff",
    "tests/unit/runtime/test_certification_optional16_guard_profile_r31_source_fake.py": R31_TEST_SHA256,
}
R31_PROFILE = R31_PACKET / "profile.json"
R31_REVIEW = E / "iteration41-optional16-r31-guard-profile-independent-review-r1-2026-10-04"
R31_REVIEW_PINS = {
    "review.json": "78dca5fafb47a96c45fcd30e517066218c82414561164f1f4ff6e143313b4568",
    "review-bundle.zip": "a370e78a3001dad5416b55490feff2b6de13d87921e3fb725f4ddf1da7951bc7",
    "review-index.json": "700bfb02e754925fe412181b69ae16973581e5829f37b2cb16724d2bfee2c708",
    "review-checkpoint.json": "37482baadeed72a4c0a3e1d9d4ff13aa13799131d3dcbde33a7678e7d55c0fef",
}
R31_REVIEW_BUNDLE_CANDIDATE_README_SHA256 = (
    "a51f41b03692c0a94119a5ddff0f8d368499e73bd54ff8e74d9863ce077faa6a"
)
R31_REVIEW_README_SHA256 = "63e35c51c6862efac778e1fe523c22f33d9c62db0688308b2630d3f7735ae2b5"
R31_REVIEW_SOURCE_PINS_SHA256 = "b6aac04cabb450626a078acdaffdf6ef2dcf960522bd65723e0848b3c07fcaa3"
R31_REVIEW_QA_SUMMARY_SHA256 = "c27efcb6ba87b9bf30793464cd69f387739638f4d7fb288bbb1d2211cf42ca53"

R33_PACKET = E / "iteration41-optional16-installed-matrix-r33-source-fake-r2-2026-10-05"
R33_PACKET_PINS = {
    "source-bundle.zip": "b2497d46cb6519c8d644f6915a3f6c9702a38b1b5d4407239ab22e99c1efb1c0",
    "source-index.json": "bfd1c4937838403eed119c85fee3bc39e971a0698305d7eba373b393b98c4168",
    "source-pins.json": "9f3f321515863116fd0d5785bf70a93a8eb3c6bddfeb9b73bc51faca9801b626",
    "checkpoint.json": "95718b6edd5b9d80c6c20d12ac652ff1f1f1251d27bc3831e52cda79874f7b3c",
    "lineage.json": "2d25f3cd30dad8bbeda8a041444ee67bfa901e5fe236b6a8bbc6587ec6939d91",
    "qa-summary.json": "2aa20cf1862be9b5e34b8ca0e958c4f6b99e74c573adc2d59e9fc1378fe4467b",
    "README.md": "a9268cd689979ca469953e97ca20d16c2d8129afdb2b87bf7f5b34fd0d63143f",
}
R33_PACKET_MEMBER_PINS = {
    "lineage.json": R33_PACKET_PINS["lineage.json"],
    "qa-summary.json": R33_PACKET_PINS["qa-summary.json"],
    "README.md": R33_PACKET_PINS["README.md"],
}
R33_CANDIDATE = (
    ROOT / "backtrader_runtime/certification_optional16_installed_matrix_r33_candidate.py"
)
R33_CANDIDATE_SHA256 = "cae6a8165353164afed45709afcaaf1e7cea136af09cca3222ea78afb9906dc5"
R33_TEST = (
    ROOT / "tests/unit/runtime/test_certification_optional16_installed_matrix_r33_source_fake.py"
)
R33_TEST_SHA256 = "a913e3380559d3f7cce7a5bf04cd281d7cce2b7752ce55b0b58b7533083f41d7"
R33_DIAGNOSTIC_TEST = (
    ROOT / "tests/unit/runtime/test_certification_optional16_installed_matrix_r33_diagnostics.py"
)
R33_DIAGNOSTIC_TEST_SHA256 = "f9e96b91d254ffe409a7e6874665ddf64073aa37ef2ed54397b6305bedf4567e"
R33_SOURCE_INDEX_SCHEMA = "iteration41.optional16.r33-matrix-source-index.v1"
R33_SOURCE_PINS_SCHEMA = "iteration41.optional16.r33-matrix-source-pins.v1"
R33_SOURCE_CHECKPOINT_SCHEMA = "iteration41.optional16.r33-matrix-source-checkpoint.v1"
R33_REVIEW = E / "iteration41-optional16-installed-matrix-r33-independent-review-r2-2026-10-05"
R33_REVIEW_PINS = {
    "review.json": "fb8f7e2da9eb9b837089b24c37da0350396510a9f8f0afd04ccb41ae002a582d",
    "review-bundle.zip": "e46f70b5d3208d1f1a094917543fa9cf89664f65f88c562ef21c9856e485edd2",
    "review-index.json": "af71156aec96e9fbecc9205254bf2fd2b5b026c3425fb6b9e86232f403cfbbdd",
    "review-checkpoint.json": "2306185c71301eb0f7efa9b15c5b917ac520a7282810c442ecd7174fb2220f66",
}
R33_REVIEW_README_SHA256 = "387a72896f2655bdae78765b14a1a519add50ab6d509ba3c32343b2109204447"

R28_PACKET = E / "iteration41-optional16-r28-guard-facts-source-fake-2026-10-04"
R28_PACKET_PINS = {
    "source-bundle.zip": "3763998358fb601e19f96be61cf3c9c573511b4f483118d66ab17b7e7fbd7e17",
    "source-index.json": "c1fd28315aadb5a02ae20e40da2fd12a98ac620e48f3266971b80378c4350d3e",
    "source-pins.json": "62c8d6d252a590c7e750d653a01c7e049d78760941156573e2230238e650efc1",
    "checkpoint.json": "9e8c8b95b5d30b3768a36cd447cc4ff41755f48169e5d95c9c3c73771b8e55e8",
}
R28_SOURCE_PINS = {
    "backtrader_runtime/manifest_index_r28_candidate.py": "841abba5583171b4560d13489f154a037793be50d624311005e945105e9967d8",
    "backtrader_runtime/certification_optional_owner_integration_r28_candidate.py": "9f5bac2b52ed01dca867b8a3db8df7856d81c3932cc50af8efc239cc77eddf52",
    "backtrader_runtime/certification_optional16_local_matrix_candidate_r28.py": "9ad1aa4bcd76c0a8a7ec12f81e00335a4edb1b0a47b3ed0b6480f43b2058da5c",
    "backtrader_runtime/certification_optional16_installed_matrix_r28.py": "b6a2980d73b69882fdf19878218c1d6a51054dfdf10ec7ac73a24ea4198be4be",
    "tests/unit/runtime/test_optional16_manifest_index_r28_guard.py": "022c2fa946f862e52fc4af57f61aa97a9296d6a379a034645393baa803b0207a",
    "tests/unit/runtime/test_certification_optional16_installed_matrix_r28_trace.py": "5c69f35490d3379007154a5616e6c364f27b1fa7b2ce63e86fb4872d86d1a52b",
}
R28_REVIEW = E / "iteration41-optional16-r28-independent-source-fake-review-r1-2026-10-04"
R28_REVIEW_PINS = {
    "review.json": "f1d8ca6a116c570d9f475052c2c19ac0edcc09962cb44de4663a8bead9f1090c",
    "review-bundle.zip": "b9222f88835d591c39bd12ec77b7da4a71d77553d520a1cde990c251ae46313e",
    "review-index.json": "bea8b33427cc23e2a3c5a0b46feac96b73e42e20e8a018914bae381b333c9d3c",
    "review-checkpoint.json": "0ee02d09dbfba0591f5053c37b1d67f721efaf82c9bbb328569836cf0c79a3ed",
}
R28_ROOT_ARTIFACT_PINS = {
    "iteration41-optional16-r28-saved-progress-projection-r1-2026-10-04/root-observation.json": "2e99442d62f019fb80f6f5b9e0f84447e7a3881e44718d88c99ebb789be65c30",
    "iteration41-optional16-r28-saved-progress-projection-r1-2026-10-04/progress.txt": "329211f3b880d56dd296225d8178098436496a3f5a91a0597c6ec0e02955d6ed",
    "iteration41-optional16-r28-root-held-invocation-r1-2026-10-04/root-observation.json": "d50485da8b13bd1fa777efb7ca1eff044d19e55f8a2ecdaad542937af3424d3c",
}
R28_LINEAGE_PINS = {
    "iteration41-optional16-r27r3-matrix-progress-source-fake-2026-10-04/source-bundle.zip": "d47d3be2c42b60eaf4a087653e7ea7967a96427367080e6514fcc4b5cde2c66b",
    "iteration41-optional16-r27r3-matrix-progress-source-fake-2026-10-04/source-index.json": "e8cf3b2abc6680e04531b02e00e74447ca337be23541d2cbed84bb9e910b17c5",
    "iteration41-optional16-r27r3-matrix-progress-source-fake-2026-10-04/source-pins.json": "4d692fb1a48310e6c8b12e132ddb716934d1edd5cd46e75fcfb45370d51b45fe",
    "iteration41-optional16-r27r3-matrix-progress-independent-review-r1-2026-10-04/review.json": "e2a8e14a58583b3bce4190f2bd336547b215b6d804bda64f8a4592c9b0727a32",
    "iteration41-optional16-r27r3-matrix-progress-independent-review-r1-2026-10-04/review-package.zip": "a62ac90871141faec38b1a8837afff487ed9153629b8992a6b7554c066226e72",
    "iteration41-optional16-r27r3-matrix-progress-independent-review-r1-2026-10-04/review-index.json": "9e3bc102fe02b374f126d272f4341ec841a5e2d998658dfe0b28af73ef49662e",
    "iteration41-optional16-r27r3-matrix-progress-independent-review-r1-2026-10-04/checkpoint.json": "61828ab068fde7cff969e7b0812a06d7503b426b043cc2391b76231de6a820de",
    "iteration41-optional16-r27r3-root-actual-safe-summary-r8-2026-10-04/root-observation.json": "90917c3ba4b91f2a4464658ce8d0549cecb6d32f1eb7ca0fa514790f6d086ec5",
}
R28_ROOT_DRIVER = Path(r"D:\temp\iteration41-optional16-r28-root-driver-r1.py")
R28_ROOT_DRIVER_SHA256 = "24d69e7fb48f4c0d86b94ef4297a7545c92643bd88990291fecf1e8a7686c327"
SNAPSHOT = (
    E
    / "iteration41-optional16-r25-root-held-installed-record-snapshot-r1-2026-10-04/installed-record-candidate.json"
)
SNAPSHOT_SHA256 = "592dc14efa159d42c6f603841d598ed8f487f4f1e83060342965d5cb2e898df6"

M01_PACKET = E / "iteration41-okx-m01-v6-r14-root-public-source-fake-r3-2026-10-04"
M01_PACKET_PINS = {
    "source-bundle.zip": "ebe72a9c66e19b302c3c030dd499e82b6194ff931c84aae13bf555f42dcb3e2e",
    "source-index.json": "2f848f25956f47b1238ec15465262d6b1219183a7b4735016c88b18afc1e3004",
    "source-checkpoint.json": "927a75f0f5278f0a7062ddee9234acdf48b6c3d9af12bdb64938ece877dad5d7",
}
M01_HELPER = M01_PACKET / "root_diagnostic_once_r14_r3_unset.py"
M01_HELPER_SHA256 = "ef83ff053fe0a94e3a8140f560bae98182d7c11a45f7d86e3ae4de088ec2af3a"
JOB = ROOT / "scripts/iteration41_okx_l03_l04_v4_root_launcher.py"
JOB_SHA256 = "0b8076f4cd8aa4419a29a0bbc3f1884e24c2610e2ba5b6cf2000c0cdf861c023"
CU = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CU_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
R2_GLUE = Path(r"D:\temp\iteration41-optional16-r32-root-held-invoke-r3.py")
R2_GLUE_SHA256 = "c93a20753db03df0710b86262b3e4a95d9a49ac5c86fe6aad055acfc945f162e"
CUV2 = CU
CUV2_SHA256 = CU_SHA256
PRIVATE_REL = "backtrader_runtime/certification_roundtrip_private.py"
PRIVATE_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
CLI_REL = "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
CLI_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"

PYTHON_EXE = Path(r"C:\anaconda3\python.exe")
PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PYTHON_DLL = Path(r"C:\anaconda3\python311.dll")
PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
PROFILER_SOFTWARE = {
    r"C:\anaconda3\Lib\cProfile.py": "0a97cf92d0e3efd2e08c2f9b0f0fb8e52a2b26978550804d8e59435201f3fa84",
    r"C:\anaconda3\Lib\profile.py": "4d87bdc8b85bf0a9bdee3e9d975a8a1a0c7360cb264fb68c4c48a102e718e3a3",
    r"C:\anaconda3\Lib\pstats.py": "d62d1e6a626ebd92187419bfe075a76997cce26fe99dd4520786d4a82b6ff10c",
}

# The independent root-driver review fills these in-memory fields.  They are
# not persisted as activated source and have no environment/CLI override.
ROOT_ENABLED = False
ROOT_REVIEWED_ACTIVATION = False
ROOT_DRIVER_SHA256 = None
DRIVER_TEST_SHA256 = None
ROOT_DRIVER_REVIEW_READY = False
ROOT_DRIVER_REVIEW_PINS = {
    "review.json": None,
    "review-bundle.zip": None,
    "review-index.json": None,
    "review-checkpoint.json": None,
    "README.md": None,
}
ROOT_DRIVER_PACKET_PINS = {
    "source-bundle.zip": None,
    "source-index.json": None,
    "source-pins.json": None,
    "checkpoint.json": None,
    "README.md": None,
    "qa/qa-summary.json": None,
}

INVOCATION_SECONDS = 60.0
CLEANUP_SECONDS = 5.0
PARENT_CAPTURE_RESERVE_SECONDS = 5.0
PARENT_DEADLINE_CLOCK_DOMAIN = "windows-cpython-3.11.5-monotonic-v1"
PARENT_DEADLINE_MONOTONIC = None
PARENT_DEADLINE_DOMAIN = None
MAX_RAW_STDOUT = 128 * 1024
MAX_RAW_STDERR = 64 * 1024
MAX_CHILD_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024
_FINAL_PREFIX = b"R33MATRIXFINAL|"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DRIVE = re.compile(r"[A-Za-z]:\Z")
_CHILD_ENV_KEYS = frozenset({"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP"})
_CHILD_PATH = r"C:\Program Files\Git\cmd;C:\Windows\System32;C:\anaconda3"
_KEEPALIVES = []


def _need(value, code="r31_root_contract"):
    if not value:
        raise RuntimeError(code)


class _ParentDeadlineBlocked(RuntimeError):
    """The R15 parent deadline is absent, invalid, or too close to honor."""


def _parent_deadline_remaining(now=None):
    """Validate the inherited Windows monotonic deadline without coercion."""
    if (
        sys.platform != "win32"
        or sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 11, 5)
    ):
        return None
    if now is None:
        now = time.monotonic()
    deadline = PARENT_DEADLINE_MONOTONIC
    if (
        type(now) is not float
        or type(deadline) is not float
        or PARENT_DEADLINE_DOMAIN != PARENT_DEADLINE_CLOCK_DOMAIN
        or not math.isfinite(now)
        or not math.isfinite(deadline)
    ):
        return None
    remaining = deadline - now
    if not math.isfinite(remaining) or not 0.0 < remaining <= 100.0:
        return None
    return remaining


def _r15_invocation_deadline(now=None):
    """Reserve R5's full 60s run, 5s cleanup, and 5s parent capture window."""
    if now is None:
        now = time.monotonic()
    remaining = _parent_deadline_remaining(now)
    required = INVOCATION_SECONDS + CLEANUP_SECONDS + PARENT_CAPTURE_RESERVE_SECONDS
    if remaining is None or remaining < required:
        raise _ParentDeadlineBlocked("parent_deadline_budget_insufficient")
    deadline = min(
        now + INVOCATION_SECONDS,
        PARENT_DEADLINE_MONOTONIC - CLEANUP_SECONDS - PARENT_CAPTURE_RESERVE_SECONDS,
    )
    if type(deadline) is not float or not math.isfinite(deadline) or deadline - now < INVOCATION_SECONDS:
        raise _ParentDeadlineBlocked("parent_deadline_budget_insufficient")
    return deadline


def _strict_zero(value):
    return type(value) is int and value == 0


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _exact_public_tree(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(
            _exact_public_tree(actual[key], value) for key, value in expected.items()
        )
    if type(expected) in (list, tuple):
        return len(actual) == len(expected) and all(
            _exact_public_tree(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def _windows_path_key(value):
    """Normalize absolute Windows paths without resolving filesystem aliases."""
    if isinstance(value, Path):
        value = os.fspath(value)
    _need(type(value) is str and value and "\x00" not in value, "pin_path_invalid")
    _need(ntpath.isabs(value), "pin_path_must_be_absolute")
    normalized = ntpath.normcase(ntpath.normpath(value))
    drive, tail = ntpath.splitdrive(normalized)
    _need(bool(drive) and tail.startswith("\\"), "pin_path_invalid")
    return normalized


def _add_path_pin(mapping, seen, duplicates, path, digest):
    key = _windows_path_key(path)
    _need(type(digest) is str and _HASH.fullmatch(digest) is not None, "pin_digest_invalid")
    previous = seen.get(key)
    if previous is not None:
        _need(previous == digest, "conflicting_path_aliases")
        duplicates[0] += 1
    else:
        seen[key] = digest
    current = mapping.get(key)
    _need(current is None or current == digest, "conflicting_path_aliases")
    mapping[key] = digest


def _read_pin(path, expected):
    _need(type(expected) is str and _HASH.fullmatch(expected) is not None, "pin_shape_invalid")
    raw = Path(path).read_bytes()
    _need(type(raw) is bytes and _sha(raw) == expected, "public_pin_mismatch")
    return raw


def _activation_ready():
    names = {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"}
    r33_names = {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json"}
    packet_names = {"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json", "README.md", "qa/qa-summary.json"}
    return (
        ROOT_ENABLED is True
        and ROOT_REVIEWED_ACTIVATION is True
        and ROOT_DRIVER_REVIEW_READY is True
        and type(ROOT_DRIVER_SHA256) is str
        and _HASH.fullmatch(ROOT_DRIVER_SHA256) is not None
        and set(ROOT_DRIVER_REVIEW_PINS) == names
        and all(type(v) is str and _HASH.fullmatch(v) for v in ROOT_DRIVER_REVIEW_PINS.values())
        and set(ROOT_DRIVER_PACKET_PINS) == packet_names
        and all(type(v) is str and _HASH.fullmatch(v) for v in ROOT_DRIVER_PACKET_PINS.values())
        and type(DRIVER_TEST_SHA256) is str
        and _HASH.fullmatch(DRIVER_TEST_SHA256) is not None
        and type(R33_REVIEW) is type(E)
        and set(R33_REVIEW_PINS) == r33_names
        and all(type(v) is str and _HASH.fullmatch(v) for v in R33_REVIEW_PINS.values())
        and type(R33_REVIEW_README_SHA256) is str
        and _HASH.fullmatch(R33_REVIEW_README_SHA256) is not None
    )


def _r19_source_member_rows():
    expected_sets = {
        **{
            path: "r16-frozen-composite"
            for path in (
                "scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py",
                "scripts/iteration41_optional16_r33_root_driver_r16.py",
                "scripts/iteration41_optional16_r33_root_held_glue_r15.py",
                "scripts/iteration41_optional16_r33_root_held_invoke_r16.py",
                "scripts/iteration41_optional16_r33_whole_call_supervisor_r16.py",
                "tests/unit/scripts/test_iteration41_optional16_r33_deadline_r16_aggregate_source_fake.py",
            )
        },
        **{
            path: "r17-frozen-composite"
            for path in (
                "scripts/iteration41_optional16_r33_deadline_r17_binding.py",
                "scripts/iteration41_optional16_r33_root_held_invoke_r17.py",
                "scripts/iteration41_optional16_r33_whole_call_supervisor_r17.py",
                "tests/unit/scripts/test_iteration41_optional16_r33_activation_r17_source_fake.py",
            )
        },
        **{path: "r18-frozen-composite" for path in (*R18_ROLE_PATHS.values(), R18_TEST_PATH)},
        **{
            path: "r19-successor"
            for path in (
                "scripts/iteration41_optional16_r33_deadline_r19_binding.py",
                "scripts/iteration41_optional16_r33_root_driver_r19.py",
                "scripts/iteration41_optional16_r33_root_held_invoke_r19.py",
                "scripts/iteration41_optional16_r33_whole_call_supervisor_r19.py",
                "tests/unit/scripts/test_iteration41_optional16_r33_activation_r19_source_fake.py",
            )
        },
    }
    raw = _read_pin(
        DRIVER_PACKET / "source-index.json",
        ROOT_DRIVER_PACKET_PINS.get("source-index.json"),
    )
    try:
        document = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _need(False, "r19_source_index_invalid")
    rows = document.get("members") if type(document) is dict else None
    _need(
        type(document) is dict
        and document.get("schema") == "iteration41.optional16.r33.deadline-r19.source-index.v1"
        and document.get("source_bundle_member_count") == len(expected_sets)
        and type(rows) is list
        and len(rows) == len(expected_sets),
        "r19_source_index_shape_invalid",
    )
    observed = {}
    for row in rows:
        _need(
            type(row) is dict
            and set(row) == {"path", "sha256", "size_bytes", "source_set"}
            and type(row["path"]) is str
            and row["path"] not in observed
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]) is not None
            and type(row["size_bytes"]) is int
            and row["size_bytes"] >= 0
            and row["source_set"] == expected_sets.get(row["path"]),
            "r19_source_index_row_invalid",
        )
        relative = Path(row["path"])
        _need(not relative.is_absolute() and ".." not in relative.parts, "r19_source_index_path_invalid")
        observed[row["path"]] = row
    _need(set(observed) == set(expected_sets), "r19_source_index_member_set_invalid")
    return rows


def _expected_pins():
    public_raw = _read_pin(ROOT_PUBLIC_PINS, ROOT_PUBLIC_PINS_SHA256)
    public_doc = json.loads(public_raw.decode("utf-8"))
    _need(
        type(public_doc) is dict
        and public_doc.get("root_enabled") is False
        and public_doc.get("sdk_imported") is False
    )
    base = public_doc.get("public_paths_sha256")
    _need(type(base) is dict and len(base) == 379, "root_public_pin_set_invalid")
    pins = {}
    software = {}
    seen = {}
    duplicates = [0]
    for path, digest in base.items():
        _add_path_pin(pins, seen, duplicates, path, digest)
    _add_path_pin(pins, seen, duplicates, ROOT_PUBLIC_PINS, ROOT_PUBLIC_PINS_SHA256)
    for folder, mapping in ((R1_PACKET, R1_PACKET_PINS), (R1_REVIEW, R1_REVIEW_PINS)):
        for name, digest in mapping.items():
            _add_path_pin(pins, seen, duplicates, folder / name, digest)
    for folder, mapping in (
        (R2_PREDECESSOR_PACKET, R2_PREDECESSOR_PACKET_PINS),
        (R2_PREDECESSOR_REVIEW, R2_PREDECESSOR_REVIEW_PINS),
    ):
        for name, digest in mapping.items():
            _add_path_pin(pins, seen, duplicates, folder / name, digest)
    for path, digest in {R1_DRIVER: R1_DRIVER_SHA256, R1_TEST: R1_TEST_SHA256}.items():
        _add_path_pin(pins, seen, duplicates, path, digest)
    for folder, mapping in (
        (R31_PACKET, R31_PACKET_PINS),
        (R31_REVIEW, R31_REVIEW_PINS),
        (R33_REVIEW, R33_REVIEW_PINS),
        (R28_PACKET, R28_PACKET_PINS),
        (R28_REVIEW, R28_REVIEW_PINS),
        (M01_PACKET, M01_PACKET_PINS),
    ):
        for name, digest in mapping.items():
            _add_path_pin(pins, seen, duplicates, folder / name, digest)
    for name in ("source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json"):
        _add_path_pin(pins, seen, duplicates, R33_PACKET / name, R33_PACKET_PINS[name])
    for name, digest in {
        "source-pins.json": R31_REVIEW_SOURCE_PINS_SHA256,
        "qa-summary.txt": R31_REVIEW_QA_SUMMARY_SHA256,
    }.items():
        _add_path_pin(pins, seen, duplicates, R31_REVIEW / name, digest)
    for path, digest in R28_ROOT_ARTIFACT_PINS.items():
        _add_path_pin(pins, seen, duplicates, E / path, digest)
    for path, digest in R28_LINEAGE_PINS.items():
        _add_path_pin(pins, seen, duplicates, E / path, digest)
    _add_path_pin(pins, seen, duplicates, R33_CANDIDATE, R33_CANDIDATE_SHA256)
    _add_path_pin(pins, seen, duplicates, R33_TEST, R33_TEST_SHA256)
    _add_path_pin(pins, seen, duplicates, R33_DIAGNOSTIC_TEST, R33_DIAGNOSTIC_TEST_SHA256)
    _add_path_pin(pins, seen, duplicates, R33_REVIEW / "README.md", R33_REVIEW_README_SHA256)
    r31_index_raw = _read_pin(
        R31_PACKET / "source-index.json", R31_PACKET_PINS["source-index.json"]
    )
    r31_index = json.loads(r31_index_raw.decode("utf-8"))
    r31_lineage = r31_index.get("lineage")
    _need(type(r31_lineage) is list and len(r31_lineage) == 32, "r31_lineage_pin_list_invalid")
    for row in r31_lineage:
        _need(
            type(row) is dict
            and set(row) == {"path", "relation", "sha256"}
            and type(row["path"]) is str
            and type(row["relation"]) is str
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]) is not None,
            "r31_lineage_pin_invalid",
        )
        relative = Path(row["path"])
        _need(not relative.is_absolute() and ".." not in relative.parts, "r31_lineage_path_invalid")
        _add_path_pin(pins, seen, duplicates, ROOT / relative, row["sha256"])
    for path, digest in R28_SOURCE_PINS.items():
        _add_path_pin(pins, seen, duplicates, ROOT / path, digest)
    for relative, digest in R31_ACTIVE_SOURCES.items():
        path = R31_PROFILE if relative == "profile.json" else ROOT / relative
        _add_path_pin(pins, seen, duplicates, path, digest)
    for path, digest in {
        R31_PROFILE_MODULE: R31_PROFILE_MODULE_SHA256,
        SNAPSHOT: SNAPSHOT_SHA256,
        R31_REVIEW / "README.md": R31_REVIEW_README_SHA256,
        R28_ROOT_DRIVER: R28_ROOT_DRIVER_SHA256,
        R2_GLUE: R2_GLUE_SHA256,
        JOB: JOB_SHA256,
        CU: CU_SHA256,
        ROOT / PRIVATE_REL: PRIVATE_SHA256,
        ROOT / CLI_REL: CLI_SHA256,
        M01_HELPER: M01_HELPER_SHA256,
    }.items():
        _add_path_pin(pins, seen, duplicates, path, digest)
    for path, digest in {
        PYTHON_EXE: PYTHON_EXE_SHA256,
        PYTHON_DLL: PYTHON_DLL_SHA256,
        **PROFILER_SOFTWARE,
    }.items():
        _add_path_pin(software, seen, duplicates, path, digest)
    if ROOT_DRIVER_REVIEW_READY is True:
        _need(
            ROOT_ENABLED is True
            and ROOT_REVIEWED_ACTIVATION is True
            and _activation_ready()
            and R33_REVIEW is not None,
            "root_review_fields_invalid",
        )
        _need(
            _windows_path_key(__file__) == _windows_path_key(ROOT_DRIVER_PATH),
            "root_driver_path_mismatch",
        )
        _add_path_pin(pins, seen, duplicates, ROOT_DRIVER_PATH, ROOT_DRIVER_SHA256)
        _add_path_pin(
            pins,
            seen,
            duplicates,
            DRIVER_TEST,
            DRIVER_TEST_SHA256,
        )
        _add_path_pin(pins, seen, duplicates, ROOT_BINDING_HELPER, ROOT_BINDING_HELPER_SHA256)
        for folder, mapping in (
            (R16_PACKET, R16_PACKET_PINS),
            (R16_REVIEW, R16_REVIEW_PINS),
            (R17_PACKET, R17_PACKET_PINS),
            (R17_REVIEW, R17_REVIEW_PINS),
            (R18_PACKET, R18_PACKET_PINS),
            (R18_REVIEW, R18_REVIEW_PINS),
        ):
            for name, digest in mapping.items():
                _add_path_pin(pins, seen, duplicates, folder / name, digest)
        for row in _r19_source_member_rows():
            _add_path_pin(pins, seen, duplicates, ROOT / row["path"], row["sha256"])
        for relative, digest in _R15_PUBLIC_EVIDENCE_PINS.items():
            _add_path_pin(pins, seen, duplicates, ROOT / relative, digest)
        for name, digest in ROOT_DRIVER_PACKET_PINS.items():
            _add_path_pin(pins, seen, duplicates, DRIVER_PACKET / name, digest)
        for name, digest in ROOT_DRIVER_REVIEW_PINS.items():
            _add_path_pin(pins, seen, duplicates, DRIVER_REVIEW / name, digest)
        for name, digest in R33_REVIEW_PINS.items():
            _add_path_pin(pins, seen, duplicates, R33_REVIEW / name, digest)
    else:
        _need(
            ROOT_ENABLED is False
            and ROOT_REVIEWED_ACTIVATION is False
            and ROOT_DRIVER_SHA256 is None
            and all(value is None for value in ROOT_DRIVER_REVIEW_PINS.values())
            and all(value is None for value in ROOT_DRIVER_PACKET_PINS.values()),
            "root_activation_must_stay_closed",
        )
    return pins, software, duplicates[0]


def _verify_disk_pins(pins):
    for name, digest in sorted(pins.items()):
        _need(
            type(name) is str
            and _windows_path_key(name) == name
            and type(digest) is str
            and _HASH.fullmatch(digest),
            "public_pin_entry_invalid",
        )
        _read_pin(name, digest)
    return len(pins)


def public_check():
    pins, software, duplicate_path_aliases = _expected_pins()
    return {
        "schema": "iteration41.optional16.r33.root-driver-r4-public-check.v1",
        "status": "PUBLIC_PINS_VERIFIED",
        "public_pin_count": _verify_disk_pins(pins),
        "runtime_pin_count": _verify_disk_pins(software),
        "same_digest_path_aliases_deduplicated": duplicate_path_aliases,
        "activation": "UNSET",
        "strict_cases_passed": 0,
        "acceptance": "NOT_ESTABLISHED",
    }


def _held(held, path):
    value = held.get(_windows_path_key(path)) if type(held) is dict else None
    _need(type(value) is bytes, "held_source_missing")
    return value


def _validate_zip(raw, members):
    _need(
        type(raw) is bytes
        and type(members) is list
        and len(members) == len({row.get("path") for row in members if type(row) is dict}),
        "archive_index_invalid",
    )
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        names = archive.namelist()
        _need(names == [row["path"] for row in members], "archive_member_set_invalid")
        contents = {}
        for row in members:
            item = archive.read(row["path"])
            _need(
                len(item) == row["bytes"] and _sha(item) == row["sha256"],
                "archive_member_hash_invalid",
            )
            contents[row["path"]] = item
    return contents


def _validate_r31_review_bundle(raw, members, held):
    """Validate every indexed R31 review-bundle member against the held source."""
    _need(type(raw) is bytes and type(members) is list, "r31_review_bundle_invalid")
    indexed = {}
    for row in members:
        _need(
            type(row) is dict
            and set(row) == {"path", "bytes", "sha256"}
            and type(row["path"]) is str
            and type(row["bytes"]) is int
            and row["bytes"] >= 0
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]) is not None,
            "r31_review_bundle_index_invalid",
        )
        _need(row["path"] not in indexed, "r31_review_bundle_duplicate_member")
        indexed[row["path"]] = row
    expected_members = {
        "candidate/source-bundle.zip": (
            R31_PACKET / "source-bundle.zip",
            R31_PACKET_PINS["source-bundle.zip"],
        ),
        "candidate/source-index.json": (
            R31_PACKET / "source-index.json",
            R31_PACKET_PINS["source-index.json"],
        ),
        "candidate/source-pins.json": (
            R31_PACKET / "source-pins.json",
            R31_PACKET_PINS["source-pins.json"],
        ),
        "candidate/checkpoint.json": (
            R31_PACKET / "checkpoint.json",
            R31_PACKET_PINS["checkpoint.json"],
        ),
        "candidate/profile.json": (R31_PACKET / "profile.json", R31_PACKET_PINS["profile.json"]),
        "candidate/README.md": (
            R31_PACKET / "README.md",
            R31_REVIEW_BUNDLE_CANDIDATE_README_SHA256,
        ),
        "candidate/qa/qa-summary.json": (
            R31_PACKET / "qa/qa-summary.json",
            R31_PACKET_PINS["qa/qa-summary.json"],
        ),
        "review.json": (R31_REVIEW / "review.json", R31_REVIEW_PINS["review.json"]),
        "source-pins.json": (R31_REVIEW / "source-pins.json", R31_REVIEW_SOURCE_PINS_SHA256),
        "qa-summary.txt": (R31_REVIEW / "qa-summary.txt", R31_REVIEW_QA_SUMMARY_SHA256),
        "README.md": (R31_REVIEW / "README.md", R31_REVIEW_README_SHA256),
    }
    _need(set(indexed) == set(expected_members), "r31_review_bundle_member_set_invalid")
    _need(
        indexed["candidate/README.md"]
        == {
            "path": "candidate/README.md",
            "bytes": 1194,
            "sha256": R31_REVIEW_BUNDLE_CANDIDATE_README_SHA256,
        },
        "r31_review_candidate_readme_unpinned",
    )
    expected_order = [row["path"] for row in members]
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        _need(archive.namelist() == expected_order, "r31_review_bundle_member_set_invalid")
        for name, (path, digest) in expected_members.items():
            item = archive.read(name)
            row = indexed[name]
            _need(
                len(item) == row["bytes"] and _sha(item) == digest and item == _held(held, path),
                "r31_review_bundle_member_hash_invalid",
            )


def _validate_candidate_review(held):
    """Validate the R31 source packet, independent review, and public lineage."""
    source_index_raw = _held(held, R31_PACKET / "source-index.json")
    source_pins_raw = _held(held, R31_PACKET / "source-pins.json")
    source_checkpoint_raw = _held(held, R31_PACKET / "checkpoint.json")
    source_bundle_raw = _held(held, R31_PACKET / "source-bundle.zip")
    _need(
        _sha(source_index_raw) == R31_PACKET_PINS["source-index.json"]
        and _sha(source_pins_raw) == R31_PACKET_PINS["source-pins.json"]
        and _sha(source_checkpoint_raw) == R31_PACKET_PINS["checkpoint.json"]
        and _sha(source_bundle_raw) == R31_PACKET_PINS["source-bundle.zip"],
        "r31_packet_pin_mismatch",
    )
    source_index = json.loads(source_index_raw.decode("utf-8"))
    source_pins = json.loads(source_pins_raw.decode("utf-8"))
    source_checkpoint = json.loads(source_checkpoint_raw.decode("utf-8"))
    source_members = source_index.get("members")
    _need(
        source_index.get("schema") == "iteration41.optional16.r31.guard-profile.source-index.v1"
        and source_index.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and source_index.get("source_bundle_member_count") == 41
        and source_index.get("case_pass") is False
        and source_index.get("registry_admission") is False
        and _strict_zero(source_index.get("strict_cases_passed"))
        and source_index.get("acceptance") == "NOT_ESTABLISHED"
        and type(source_members) is list
        and len(source_members) == 41,
        "r31_source_index_contract_invalid",
    )
    _validate_zip(source_bundle_raw, source_members)

    expected_source_fields = {
        "schema": "iteration41.optional16.r31.guard-profile.source-pins.v1",
        "root_enabled": False,
        "root_reviewed_activation": False,
        "root_review_ready": False,
        "root_review_pins": {
            "review.json": None,
            "review-bundle.zip": None,
            "review-index.json": None,
            "review-checkpoint.json": None,
        },
        "strict_cases_passed": 0,
        "acceptance": "NOT_ESTABLISHED",
        "case_pass": False,
        "registry_admission": False,
        "source_bundle_member_count": 41,
        "sources": R31_ACTIVE_SOURCES,
    }
    _need(
        all(source_pins.get(key) == value for key, value in expected_source_fields.items()),
        "r31_source_pins_contract_invalid",
    )
    _need(
        source_checkpoint.get("schema") == "iteration41.optional16.r31.guard-profile.checkpoint.v1"
        and source_checkpoint.get("candidate_status") == source_index["candidate_status"]
        and source_checkpoint.get("source_bundle_member_count") == 41
        and source_checkpoint.get("source_bundle_sha256") == R31_PACKET_PINS["source-bundle.zip"]
        and source_checkpoint.get("source_index_sha256") == R31_PACKET_PINS["source-index.json"]
        and source_checkpoint.get("source_pins_sha256") == R31_PACKET_PINS["source-pins.json"]
        and source_checkpoint.get("candidate_hashes") == R31_ACTIVE_SOURCES
        and source_checkpoint.get("acceptance") == "NOT_ESTABLISHED"
        and source_checkpoint.get("case_pass") is False
        and source_checkpoint.get("registry_admission") is False
        and _strict_zero(source_checkpoint.get("strict_cases_passed")),
        "r31_source_checkpoint_contract_invalid",
    )

    for relative, digest in R31_ACTIVE_SOURCES.items():
        path = R31_PROFILE if relative == "profile.json" else ROOT / relative
        _need(_sha(_held(held, path)) == digest, "r31_active_source_mismatch")
    _need(
        _sha(_held(held, R31_PROFILE_MODULE)) == R31_PROFILE_MODULE_SHA256,
        "r31_profile_archive_copy_mismatch",
    )
    _need(
        _sha(_held(held, R31_MATRIX)) == R31_MATRIX_SHA256
        and _sha(_held(held, R31_OWNER)) == R31_OWNER_SHA256
        and _sha(_held(held, R31_TEST)) == R31_TEST_SHA256,
        "r31_active_workspace_source_mismatch",
    )
    profile_raw = _held(held, R31_PROFILE)
    profile_document = json.loads(profile_raw.decode("utf-8"))
    _need(
        _canonical(profile_document) == profile_raw
        and profile_document.get("schema")
        == "iteration41.optional16.r31.guard-profile-definition.v1"
        and profile_document.get("r30_helper_sha256") == R31_MATRIX_SHA256
        and profile_document.get("installed_record_snapshot_sha256") == SNAPSHOT_SHA256
        and profile_document.get("guard_calls") == 10
        and profile_document.get("matrix_or_service_construction") is False
        and profile_document.get("provider_or_transport_calls") is False
        and _strict_zero(profile_document.get("strict_cases_passed"))
        and profile_document.get("acceptance") == "NOT_ESTABLISHED",
        "r31_profile_descriptor_invalid",
    )

    review_raw = _held(held, R31_REVIEW / "review.json")
    review_index_raw = _held(held, R31_REVIEW / "review-index.json")
    review_checkpoint_raw = _held(held, R31_REVIEW / "review-checkpoint.json")
    review_bundle_raw = _held(held, R31_REVIEW / "review-bundle.zip")
    _need(
        _sha(review_raw) == R31_REVIEW_PINS["review.json"]
        and _sha(review_index_raw) == R31_REVIEW_PINS["review-index.json"]
        and _sha(review_checkpoint_raw) == R31_REVIEW_PINS["review-checkpoint.json"]
        and _sha(review_bundle_raw) == R31_REVIEW_PINS["review-bundle.zip"],
        "r31_review_pin_mismatch",
    )
    review = json.loads(review_raw.decode("utf-8"))
    review_source_pins_raw = _held(held, R31_REVIEW / "source-pins.json")
    _need(
        _sha(review_source_pins_raw) == R31_REVIEW_SOURCE_PINS_SHA256,
        "r31_review_source_pins_hash_invalid",
    )
    review_source_pins = json.loads(review_source_pins_raw.decode("utf-8"))
    review_index = json.loads(review_index_raw.decode("utf-8"))
    review_checkpoint = json.loads(review_checkpoint_raw.decode("utf-8"))
    expected_candidate = {
        "candidate_sha256": R31_CANDIDATE_SHA256,
        "checkpoint_sha256": R31_PACKET_PINS["checkpoint.json"],
        "profile_descriptor_sha256": R31_PACKET_PINS["profile.json"],
        "profile_sha256": R31_PACKET_PINS["profile.json"],
        "r30_matrix_sha256": R31_MATRIX_SHA256,
        "r30_owner_sha256": R31_OWNER_SHA256,
        "source_bundle_bytes": 2442188,
        "source_bundle_sha256": R31_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R31_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R31_PACKET_PINS["source-pins.json"],
        "test_sha256": R31_TEST_SHA256,
    }
    _need(
        set(review)
        == {
            "acceptance",
            "basis",
            "candidate",
            "case_pass",
            "classification",
            "decision",
            "findings",
            "limitations",
            "registry_admission",
            "review_scope",
            "schema",
            "strict_cases_passed",
        }
        and review.get("schema") == "iteration41.optional16.r31.guard-profile.independent-review.v1"
        and review.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and review.get("classification") == "SOURCE_FAKE_ONLY_NOT_ACCEPTANCE"
        and review.get("acceptance") == "NOT_ESTABLISHED"
        and _strict_zero(review.get("strict_cases_passed"))
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and review.get("findings") == []
        and review.get("candidate") == expected_candidate,
        "r31_independent_review_invalid",
    )
    scope = review.get("review_scope")
    _need(
        type(scope) is dict
        and set(scope)
        == {
            "activated_candidate_process_run",
            "candidate_archive_members_verified",
            "candidate_workspace_source_members_verified",
            "credentials_or_private_inputs_read",
            "focused_tests",
            "in_memory_python_ast_members",
            "installed_sdk_or_native_execution",
            "provider_or_network_used",
            "public_wheel_payload_bytes_read",
            "ruff",
            "source_fake_only",
            "winapi_used",
        }
        and scope.get("candidate_archive_members_verified") == 41
        and scope.get("candidate_workspace_source_members_verified") == 6
        and scope.get("activated_candidate_process_run") is False
        and scope.get("credentials_or_private_inputs_read") is False
        and scope.get("installed_sdk_or_native_execution") is False
        and scope.get("provider_or_network_used") is False
        and scope.get("public_wheel_payload_bytes_read") is False
        and scope.get("source_fake_only") is True
        and scope.get("focused_tests") == "9 passed; 1 pre-existing pytest configuration warning"
        and scope.get("in_memory_python_ast_members") == 6
        and scope.get("ruff") == "passed"
        and scope.get("winapi_used") is False,
        "r31_review_scope_invalid",
    )
    _need(
        set(review_index)
        == {
            "acceptance",
            "candidate_bundle_sha256",
            "candidate_checkpoint_sha256",
            "candidate_index_sha256",
            "candidate_pins_sha256",
            "decision",
            "members",
            "review_bundle_sha256",
            "schema",
            "strict_cases_passed",
        }
        and review_index.get("schema")
        == "iteration41.optional16.r31.guard-profile.independent-review-index.v1"
        and review_index.get("acceptance") == "NOT_ESTABLISHED"
        and review_index.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and _strict_zero(review_index.get("strict_cases_passed"))
        and review_index.get("candidate_bundle_sha256") == R31_PACKET_PINS["source-bundle.zip"]
        and review_index.get("candidate_checkpoint_sha256") == R31_PACKET_PINS["checkpoint.json"]
        and review_index.get("candidate_index_sha256") == R31_PACKET_PINS["source-index.json"]
        and review_index.get("candidate_pins_sha256") == R31_PACKET_PINS["source-pins.json"]
        and review_index.get("review_bundle_sha256") == R31_REVIEW_PINS["review-bundle.zip"]
        and type(review_index.get("members")) is list,
        "r31_review_index_invalid",
    )
    expected_workspace_sources = {
        path: digest for path, digest in R31_ACTIVE_SOURCES.items() if path != "profile.json"
    }
    reviewed_workspace = review_source_pins.get("reviewed_workspace_members")
    _need(
        type(reviewed_workspace) is list
        and len(reviewed_workspace) == 6
        and all(type(row) is dict and set(row) == {"path", "sha256"} for row in reviewed_workspace)
        and {row["path"]: row["sha256"] for row in reviewed_workspace}
        == expected_workspace_sources,
        "r31_review_current_source_pins_invalid",
    )
    expected_candidate_path = R31_PACKET.relative_to(ROOT).as_posix()
    _need(
        set(review_source_pins)
        == {
            "acceptance",
            "candidate_checkpoint_sha256",
            "candidate_member_count",
            "candidate_packet_path",
            "candidate_profile_sha256",
            "candidate_qa_summary_sha256",
            "candidate_source_bundle_sha256",
            "candidate_source_index_sha256",
            "candidate_source_pins_sha256",
            "candidate_source_rows",
            "decision",
            "reviewed_workspace_members",
            "schema",
            "strict_cases_passed",
        }
        and review_source_pins.get("schema")
        == "iteration41.optional16.r31.guard-profile.independent-review-source-pins.v1"
        and review_source_pins.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and review_source_pins.get("acceptance") == "NOT_ESTABLISHED"
        and _strict_zero(review_source_pins.get("strict_cases_passed"))
        and review_source_pins.get("candidate_member_count") == 41
        and review_source_pins.get("candidate_packet_path") == expected_candidate_path
        and review_source_pins.get("candidate_checkpoint_sha256")
        == R31_PACKET_PINS["checkpoint.json"]
        and review_source_pins.get("candidate_profile_sha256") == R31_PACKET_PINS["profile.json"]
        and review_source_pins.get("candidate_qa_summary_sha256")
        == R31_PACKET_PINS["qa/qa-summary.json"]
        and review_source_pins.get("candidate_source_bundle_sha256")
        == R31_PACKET_PINS["source-bundle.zip"]
        and review_source_pins.get("candidate_source_index_sha256")
        == R31_PACKET_PINS["source-index.json"]
        and review_source_pins.get("candidate_source_pins_sha256")
        == R31_PACKET_PINS["source-pins.json"]
        and review_source_pins.get("candidate_source_rows") == R31_ACTIVE_SOURCES,
        "r31_review_source_pins_invalid",
    )
    _validate_r31_review_bundle(review_bundle_raw, review_index["members"], held)
    _need(
        set(review_checkpoint)
        == {
            "acceptance",
            "candidate_bundle_sha256",
            "candidate_index_sha256",
            "classification",
            "decision",
            "qa_summary_sha256",
            "readme_sha256",
            "review_bundle_sha256",
            "review_index_sha256",
            "review_sha256",
            "schema",
            "source_pins_sha256",
            "strict_cases_passed",
        }
        and review_checkpoint.get("schema")
        == "iteration41.optional16.r31.guard-profile.independent-review-checkpoint.v1"
        and review_checkpoint.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and review_checkpoint.get("acceptance") == "NOT_ESTABLISHED"
        and review_checkpoint.get("classification") == "SOURCE_FAKE_ONLY_NOT_ACCEPTANCE"
        and _strict_zero(review_checkpoint.get("strict_cases_passed"))
        and review_checkpoint.get("review_sha256") == R31_REVIEW_PINS["review.json"]
        and review_checkpoint.get("review_index_sha256") == R31_REVIEW_PINS["review-index.json"]
        and review_checkpoint.get("review_bundle_sha256") == R31_REVIEW_PINS["review-bundle.zip"]
        and review_checkpoint.get("qa_summary_sha256") == R31_REVIEW_QA_SUMMARY_SHA256
        and review_checkpoint.get("readme_sha256") == R31_REVIEW_README_SHA256
        and review_checkpoint.get("candidate_bundle_sha256") == R31_PACKET_PINS["source-bundle.zip"]
        and review_checkpoint.get("candidate_index_sha256") == R31_PACKET_PINS["source-index.json"]
        and review_checkpoint.get("source_pins_sha256") == R31_REVIEW_SOURCE_PINS_SHA256,
        "r31_review_checkpoint_invalid",
    )

    for row in source_index.get("lineage", []):
        path = ROOT / Path(row["path"])
        _need(_sha(_held(held, path)) == row["sha256"], "r31_lineage_mismatch")
    return review


def _held_json(held, path, digest, code):
    raw = _held(held, path)
    _need(_sha(raw) == digest, code)
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        raise RuntimeError(code) from None
    _need(type(value) is dict, code)
    return value


def _member_hashes(members, expected_count, code):
    _need(type(members) is list and len(members) == expected_count, code)
    result = {}
    for row in members:
        _need(
            type(row) is dict
            and set(row) == {"path", "bytes", "sha256"}
            and type(row["path"]) is str
            and row["path"]
            and type(row["bytes"]) is int
            and row["bytes"] >= 0
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]),
            code,
        )
        _need(row["path"] not in result, code)
        result[row["path"]] = row["sha256"]
    return result


def _r1_lineage_descriptor():
    return {
        "driver_sha256": R1_DRIVER_SHA256,
        "test_sha256": R1_TEST_SHA256,
        "packet": {"directory": R1_PACKET.name, **R1_PACKET_PINS},
        "review": {"directory": R1_REVIEW.name, **R1_REVIEW_PINS},
    }


def _r2_predecessor_descriptor():
    """Bind the exact immutable R2 source packet and its independent HOLD."""
    return {
        "driver_sha256": "c439a9884f537998329d9cf9408e53b6fbf0052820a5e0ea2d5b302f312aadff",
        "test_sha256": "7d542974926a75364b7bd27a7cdbbea90ade16c91ab934de7d87eeaebb35db84",
        "packet": {"directory": R2_PREDECESSOR_PACKET.name, **R2_PREDECESSOR_PACKET_PINS},
        "review": {
            "directory": R2_PREDECESSOR_REVIEW.name,
            **R2_PREDECESSOR_REVIEW_PINS,
        },
        "verdict": "HOLD_SOURCE_FAKE_ONLY",
    }


def _r33_lineage_descriptor():
    return {
        "directory": R33_PACKET.name,
        "candidate_sha256": R33_CANDIDATE_SHA256,
        "test_sha256": R33_TEST_SHA256,
        "packet": dict(R33_PACKET_PINS),
        "review": dict(R33_REVIEW_PINS),
    }


def _r5_lineage_document(held):
    return {
        "schema": "iteration41.optional16.r33.root-driver-r5.lineage.v1",
        "upstream_r1_lineage": _r1_lineage_descriptor(),
        "upstream_r2_hold_lineage": _r2_predecessor_descriptor(),
        "upstream_r33_lineage": _r33_lineage_descriptor(),
        "fixed_external_public_sources": [
            {
                "path": str(R2_GLUE),
                "sha256": R2_GLUE_SHA256,
                "bytes": len(_held(held, R2_GLUE)),
            },
            {
                "path": str(CUV2),
                "sha256": CUV2_SHA256,
                "bytes": len(_held(held, CUV2)),
            },
        ],
        "acceptance": {
            "strict_cases_passed": 0,
            "case_pass": False,
            "registry_admission": False,
            "status": "NOT_ACCEPTED_OPTIONAL16",
        },
    }


def _validate_r1_upstream_lineage(held):
    """Verify the immutable R1 source packet and its independent GO from held bytes."""
    packet_raw = {name: _held(held, R1_PACKET / name) for name in R1_PACKET_PINS}
    _need(
        all(_sha(raw) == R1_PACKET_PINS[name] for name, raw in packet_raw.items()),
        "r1_lineage_packet_pin_mismatch",
    )
    source_index = json.loads(packet_raw["source-index.json"].decode("utf-8"))
    source_pins = json.loads(packet_raw["source-pins.json"].decode("utf-8"))
    source_checkpoint = json.loads(packet_raw["checkpoint.json"].decode("utf-8"))
    member_hashes = _member_hashes(
        source_index.get("members"), 4, "r1_lineage_source_members_invalid"
    )
    _need(
        set(source_index)
        == {
            "schema",
            "candidate_status",
            "source_bundle_member_count",
            "source_bundle_sha256",
            "members",
        }
        and source_index.get("schema")
        == "iteration41.optional16.r32.root-driver-r1.source-index.v1"
        and source_index.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and source_index.get("source_bundle_member_count") == 4
        and source_index.get("source_bundle_sha256") == R1_PACKET_PINS["source-bundle.zip"]
        and member_hashes == R1_PACKET_MEMBER_PINS,
        "r1_lineage_source_index_invalid",
    )
    archived = _validate_zip(packet_raw["source-bundle.zip"], source_index["members"])
    _need(
        set(archived) == set(R1_PACKET_MEMBER_PINS)
        and all(_sha(archived[name]) == digest for name, digest in R1_PACKET_MEMBER_PINS.items()),
        "r1_lineage_source_archive_invalid",
    )
    expected_source_pins = {
        "schema": "iteration41.optional16.r32.root-driver-r1.source-pins.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "case_pass": False,
        "registry_admission": False,
        "root_enabled": False,
        "root_reviewed_activation": False,
        "root_review_ready": False,
        "strict_cases_passed": 0,
        "source_bundle_member_count": 4,
        "source_bundle_sha256": R1_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R1_PACKET_PINS["source-index.json"],
        "active_sources": {
            "scripts/iteration41_optional16_r32_matrix_root_driver_r1.py": R1_DRIVER_SHA256,
            "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r1.py": R1_TEST_SHA256,
        },
        "fresh_control_path": r"D:\temp\iteration41-optional16-r32-root-control-r1",
        "fresh_scratch_path": r"D:\temp\iteration41-optional16-r32-matrix-scratch-r1",
        "root_driver_path": r"D:\temp\iteration41-optional16-r32-root-driver-r1.py",
        "r32_candidate_sha256": "a55a77bd16d65853fac03cbc689159fd66fc4f526b20ce68e9e396fe48d20c0f",
        "r32_review_json_sha256": "e186aac28a9bd33177254299af8ef41a09a563127e1c77a88db51df9b8ab364d",
        "r32_source_bundle_sha256": "f08554f7f524a69469ec5cf431b8a5185e6cbc59e576b79496268c768ae4c804",
    }
    _need(source_pins == expected_source_pins, "r1_lineage_source_pins_invalid")
    expected_source_checkpoint = {
        "schema": "iteration41.optional16.r32.root-driver-r1.checkpoint.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "case_pass": False,
        "registry_admission": False,
        "root_enabled": False,
        "strict_cases_passed": 0,
        "source_bundle_member_count": 4,
        "source_bundle_sha256": R1_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R1_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R1_PACKET_PINS["source-pins.json"],
        "candidate_hashes": {
            "scripts/iteration41_optional16_r32_matrix_root_driver_r1.py": R1_DRIVER_SHA256,
            "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r1.py": R1_TEST_SHA256,
        },
    }
    _need(source_checkpoint == expected_source_checkpoint, "r1_lineage_source_checkpoint_invalid")

    review_raw = _held(held, R1_REVIEW / "review.json")
    review_index_raw = _held(held, R1_REVIEW / "review-index.json")
    review_checkpoint_raw = _held(held, R1_REVIEW / "review-checkpoint.json")
    review_bundle_raw = _held(held, R1_REVIEW / "review-bundle.zip")
    _need(
        _sha(review_raw) == R1_REVIEW_PINS["review.json"]
        and _sha(review_index_raw) == R1_REVIEW_PINS["review-index.json"]
        and _sha(review_checkpoint_raw) == R1_REVIEW_PINS["review-checkpoint.json"]
        and _sha(review_bundle_raw) == R1_REVIEW_PINS["review-bundle.zip"],
        "r1_lineage_review_pin_mismatch",
    )
    review = json.loads(review_raw.decode("utf-8"))
    review_index = json.loads(review_index_raw.decode("utf-8"))
    review_checkpoint = json.loads(review_checkpoint_raw.decode("utf-8"))
    candidate = review.get("candidate")
    expected_candidate = {
        "checkpoint_sha256": R1_PACKET_PINS["checkpoint.json"],
        "driver_sha256": R1_DRIVER_SHA256,
        "r28_candidate_sha256": R28_SOURCE_PINS[
            "backtrader_runtime/certification_optional16_installed_matrix_r28.py"
        ],
        "r31_profile_core_sha256": R31_CANDIDATE_SHA256,
        "r32_candidate_sha256": "a55a77bd16d65853fac03cbc689159fd66fc4f526b20ce68e9e396fe48d20c0f",
        "r32_checkpoint_sha256": "e7da081eb7388f11325656ec20a9a733642118c1d0a4ba5b988fd5342337538d",
        "r32_review_bundle_sha256": "d8ebcecd06b248c66fb149e4da0659a03843fd2941578c9fb95a8b35e80ea2cd",
        "r32_review_checkpoint_sha256": "183402250974b73a8aea8868fc857c223386c2fe67f4914f3687a5a86d357545",
        "r32_review_index_sha256": "eff428bfc9a9d3de9d43e6f3d3e23d918929386380ab87ac642df1ea3a33b8ef",
        "r32_review_json_sha256": "e186aac28a9bd33177254299af8ef41a09a563127e1c77a88db51df9b8ab364d",
        "r32_source_bundle_sha256": "f08554f7f524a69469ec5cf431b8a5185e6cbc59e576b79496268c768ae4c804",
        "r32_source_index_sha256": "7455a49ad1ad5804233fd63e8a6099757a6bba039bcfd48b9706f4f534a300f7",
        "r32_source_pins_sha256": "bab662e0efc082c6e9dd8be1f1ce3963cab033da743adc3ff34fb20c33b86faa",
        "r32_test_sha256": "c87fcecd69c43638d05f5f348203dc72f568c0583cacdde54e253cb16c5eb9ae",
        "source_bundle_sha256": R1_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R1_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R1_PACKET_PINS["source-pins.json"],
        "test_sha256": R1_TEST_SHA256,
    }
    _need(
        type(review) is dict
        and review.get("schema")
        == "iteration41.optional16.r32.root-driver-r1.independent-source-fake-review.v1"
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and review.get("strict_cases_passed") == 0
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and candidate == expected_candidate,
        "r1_lineage_review_contract_invalid",
    )
    _need(
        set(review_index)
        == {
            "checkpoint_sha256",
            "members",
            "review_bundle_sha256",
            "review_json_sha256",
            "schema",
            "source_bundle_sha256",
            "source_index_sha256",
            "source_pins_sha256",
            "verdict",
        }
        and review_index.get("schema")
        == "iteration41.optional16.r32.root-driver-r1.review-index.v1"
        and review_index.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_index.get("review_json_sha256") == R1_REVIEW_PINS["review.json"]
        and review_index.get("review_bundle_sha256") == R1_REVIEW_PINS["review-bundle.zip"]
        and review_index.get("source_bundle_sha256") == R1_PACKET_PINS["source-bundle.zip"]
        and review_index.get("source_index_sha256") == R1_PACKET_PINS["source-index.json"]
        and review_index.get("source_pins_sha256") == R1_PACKET_PINS["source-pins.json"]
        and review_index.get("checkpoint_sha256") == R1_PACKET_PINS["checkpoint.json"],
        "r1_lineage_review_index_invalid",
    )
    _validate_zip(review_bundle_raw, review_index["members"])
    _need(
        type(review_checkpoint) is dict
        and review_checkpoint.get("schema")
        == "iteration41.optional16.r32.root-driver-r1.review-checkpoint.v1"
        and review_checkpoint.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_checkpoint.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and review_checkpoint.get("strict_cases_passed") == 0
        and review_checkpoint.get("review_json_sha256") == R1_REVIEW_PINS["review.json"]
        and review_checkpoint.get("review_index_sha256") == R1_REVIEW_PINS["review-index.json"]
        and review_checkpoint.get("review_bundle_sha256") == R1_REVIEW_PINS["review-bundle.zip"]
        and review_checkpoint.get("source_bundle_sha256") == R1_PACKET_PINS["source-bundle.zip"]
        and review_checkpoint.get("source_index_sha256") == R1_PACKET_PINS["source-index.json"]
        and review_checkpoint.get("source_pins_sha256") == R1_PACKET_PINS["source-pins.json"]
        and review_checkpoint.get("candidate_sha256") == R1_DRIVER_SHA256
        and review_checkpoint.get("test_sha256") == R1_TEST_SHA256,
        "r1_lineage_review_checkpoint_invalid",
    )
    return review


def _validate_r2_predecessor_lineage(held):
    """Require the exact superseded R2 source packet and its independent HOLD."""
    packet_files = {
        name: _held(held, R2_PREDECESSOR_PACKET / name) for name in R2_PREDECESSOR_PACKET_PINS
    }
    _need(
        all(_sha(raw) == R2_PREDECESSOR_PACKET_PINS[name] for name, raw in packet_files.items()),
        "r2_predecessor_packet_pin_mismatch",
    )
    packet_index = json.loads(packet_files["source-index.json"].decode("utf-8"))
    packet_members = _member_hashes(
        packet_index.get("members"), 4, "r2_predecessor_member_rows_invalid"
    )
    expected_sources = {
        "scripts/iteration41_optional16_r32_matrix_root_driver_r2.py": "c439a9884f537998329d9cf9408e53b6fbf0052820a5e0ea2d5b302f312aadff",
        "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r2.py": "7d542974926a75364b7bd27a7cdbbea90ade16c91ab934de7d87eeaebb35db84",
    }
    expected_members = {
        "README.md": _sha(packet_files["README.md"]),
        "qa/qa-summary.json": _sha(packet_files["qa/qa-summary.json"]),
        **expected_sources,
    }
    _need(
        set(packet_index)
        == {
            "schema",
            "candidate_status",
            "source_bundle_member_count",
            "source_bundle_sha256",
            "members",
            "upstream_r1_lineage",
        }
        and packet_index.get("schema")
        == "iteration41.optional16.r32.root-driver-r2.source-index.v1"
        and packet_index.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and packet_index.get("source_bundle_member_count") == 4
        and packet_index.get("source_bundle_sha256")
        == R2_PREDECESSOR_PACKET_PINS["source-bundle.zip"]
        and packet_index.get("upstream_r1_lineage") == _r1_lineage_descriptor()
        and packet_members == expected_members,
        "r2_predecessor_source_index_invalid",
    )
    archived = _validate_zip(packet_files["source-bundle.zip"], packet_index["members"])
    _need(
        set(packet_members)
        == {
            "README.md",
            "qa/qa-summary.json",
            "scripts/iteration41_optional16_r32_matrix_root_driver_r2.py",
            "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r2.py",
        }
        and all(_sha(archived[name]) == digest for name, digest in packet_members.items()),
        "r2_predecessor_source_archive_invalid",
    )

    review_files = {
        name: _held(held, R2_PREDECESSOR_REVIEW / name) for name in R2_PREDECESSOR_REVIEW_PINS
    }
    _need(
        all(_sha(raw) == R2_PREDECESSOR_REVIEW_PINS[name] for name, raw in review_files.items()),
        "r2_predecessor_review_pin_mismatch",
    )
    review = json.loads(review_files["review.json"].decode("utf-8"))
    index = json.loads(review_files["review-index.json"].decode("utf-8"))
    checkpoint = json.loads(review_files["review-checkpoint.json"].decode("utf-8"))
    _need(
        type(review) is dict
        and review.get("schema")
        == "iteration41.optional16.r32.root-driver-r2.independent-source-fake-review.v1"
        and review.get("verdict") == "HOLD_SOURCE_FAKE_ONLY"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and _strict_zero(review.get("strict_cases_passed"))
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and type(review.get("candidate")) is dict
        and review["candidate"].get("driver_sha256")
        == expected_sources["scripts/iteration41_optional16_r32_matrix_root_driver_r2.py"]
        and review["candidate"].get("test_sha256")
        == expected_sources[
            "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r2.py"
        ]
        and review["candidate"].get("source_bundle_sha256")
        == R2_PREDECESSOR_PACKET_PINS["source-bundle.zip"],
        "r2_predecessor_review_contract_invalid",
    )
    review_members = index.get("members") if type(index) is dict else None
    member_hashes = _member_hashes(review_members, 34, "r2_predecessor_review_member_rows_invalid")
    _need(
        set(index)
        == {
            "checkpoint_sha256",
            "members",
            "review_bundle_sha256",
            "review_json_sha256",
            "schema",
            "source_bundle_sha256",
            "source_index_sha256",
            "source_pins_sha256",
            "verdict",
        }
        and index.get("schema") == "iteration41.optional16.r32.root-driver-r2.review-index.v1"
        and index.get("verdict") == "HOLD_SOURCE_FAKE_ONLY"
        and index.get("review_json_sha256") == R2_PREDECESSOR_REVIEW_PINS["review.json"]
        and index.get("review_bundle_sha256") == R2_PREDECESSOR_REVIEW_PINS["review-bundle.zip"]
        and index.get("source_bundle_sha256") == R2_PREDECESSOR_PACKET_PINS["source-bundle.zip"]
        and index.get("source_index_sha256") == R2_PREDECESSOR_PACKET_PINS["source-index.json"]
        and index.get("source_pins_sha256") == R2_PREDECESSOR_PACKET_PINS["source-pins.json"]
        and index.get("checkpoint_sha256") == R2_PREDECESSOR_PACKET_PINS["checkpoint.json"]
        and member_hashes.get("review.json") == R2_PREDECESSOR_REVIEW_PINS["review.json"],
        "r2_predecessor_review_index_invalid",
    )
    _validate_zip(review_files["review-bundle.zip"], review_members)
    _need(
        type(checkpoint) is dict
        and checkpoint.get("schema")
        == "iteration41.optional16.r32.root-driver-r2.review-checkpoint.v1"
        and checkpoint.get("verdict") == "HOLD_SOURCE_FAKE_ONLY"
        and checkpoint.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and _strict_zero(checkpoint.get("strict_cases_passed"))
        and checkpoint.get("review_json_sha256") == R2_PREDECESSOR_REVIEW_PINS["review.json"]
        and checkpoint.get("review_bundle_sha256")
        == R2_PREDECESSOR_REVIEW_PINS["review-bundle.zip"]
        and checkpoint.get("review_index_sha256") == R2_PREDECESSOR_REVIEW_PINS["review-index.json"]
        and checkpoint.get("candidate_sha256")
        == expected_sources["scripts/iteration41_optional16_r32_matrix_root_driver_r2.py"]
        and checkpoint.get("test_sha256")
        == expected_sources[
            "tests/unit/scripts/test_iteration41_optional16_r32_matrix_root_driver_r2.py"
        ],
        "r2_predecessor_review_checkpoint_invalid",
    )
    return review


def _r28_expected_member_hashes():
    return {
        "README.md": "8b62a2683475f24731871ae71960a09790bc7aec60656c35a07c8c8de8584fe3",
        "candidate/certification_optional16_installed_matrix_r28.py": R28_SOURCE_PINS[
            "backtrader_runtime/certification_optional16_installed_matrix_r28.py"
        ],
        "candidate/certification_optional16_local_matrix_candidate_r28.py": R28_SOURCE_PINS[
            "backtrader_runtime/certification_optional16_local_matrix_candidate_r28.py"
        ],
        "candidate/certification_optional_owner_integration_r28_candidate.py": R28_SOURCE_PINS[
            "backtrader_runtime/certification_optional_owner_integration_r28_candidate.py"
        ],
        "candidate/manifest_index_r28_candidate.py": R28_SOURCE_PINS[
            "backtrader_runtime/manifest_index_r28_candidate.py"
        ],
        "qa/qa-summary.json": "8fb377a0ee1c22154a63b0ae58f79f2c59226eba7c804e249cc5b8bd2d8e65d9",
        "references/r27r3/review-checkpoint.json": "61828ab068fde7cff969e7b0812a06d7503b426b043cc2391b76231de6a820de",
        "references/r27r3/review-index.json": "9e3bc102fe02b374f126d272f4341ec841a5e2d998658dfe0b28af73ef49662e",
        "references/r27r3/review.json": "e2a8e14a58583b3bce4190f2bd336547b215b6d804bda64f8a4592c9b0727a32",
        "references/r27r3/root-safe-observation.json": "90917c3ba4b91f2a4464658ce8d0549cecb6d32f1eb7ca0fa514790f6d086ec5",
        "tests/test_certification_optional16_installed_matrix_r28_trace.py": R28_SOURCE_PINS[
            "tests/unit/runtime/test_certification_optional16_installed_matrix_r28_trace.py"
        ],
        "tests/test_optional16_manifest_index_r28_guard.py": R28_SOURCE_PINS[
            "tests/unit/runtime/test_optional16_manifest_index_r28_guard.py"
        ],
    }


def _r28_expected_review_member_hashes():
    return {
        "README.md": "b6bc00803db6ab6ca77e2f33db3fe3d15f8f0a8d6b5155f975acdd871aea934d",
        "candidate-checkpoint.json": R28_PACKET_PINS["checkpoint.json"],
        "candidate-qa-summary.json": "8fb377a0ee1c22154a63b0ae58f79f2c59226eba7c804e249cc5b8bd2d8e65d9",
        "candidate-source-bundle.zip": R28_PACKET_PINS["source-bundle.zip"],
        "candidate-source-index.json": R28_PACKET_PINS["source-index.json"],
        "candidate-source-pins.json": R28_PACKET_PINS["source-pins.json"],
        "review.json": R28_REVIEW_PINS["review.json"],
    }


def _validate_r28_lineage(held):
    """Validate the immutable R28 packet against its real nested schemas."""
    packet_raw = _held(held, R28_PACKET / "source-bundle.zip")
    index = _held_json(
        held,
        R28_PACKET / "source-index.json",
        R28_PACKET_PINS["source-index.json"],
        "r28_packet_index_invalid",
    )
    pins = _held_json(
        held,
        R28_PACKET / "source-pins.json",
        R28_PACKET_PINS["source-pins.json"],
        "r28_packet_pins_invalid",
    )
    candidate_checkpoint = _held_json(
        held,
        R28_PACKET / "checkpoint.json",
        R28_PACKET_PINS["checkpoint.json"],
        "r28_candidate_checkpoint_invalid",
    )
    review = _held_json(
        held, R28_REVIEW / "review.json", R28_REVIEW_PINS["review.json"], "r28_review_invalid"
    )
    review_index = _held_json(
        held,
        R28_REVIEW / "review-index.json",
        R28_REVIEW_PINS["review-index.json"],
        "r28_review_index_invalid",
    )
    review_checkpoint = _held_json(
        held,
        R28_REVIEW / "review-checkpoint.json",
        R28_REVIEW_PINS["review-checkpoint.json"],
        "r28_review_checkpoint_invalid",
    )
    review_archive = _held(held, R28_REVIEW / "review-bundle.zip")
    snapshot = _held_json(held, SNAPSHOT, SNAPSHOT_SHA256, "r28_snapshot_invalid")

    _need(_sha(packet_raw) == R28_PACKET_PINS["source-bundle.zip"], "r28_packet_bundle_invalid")
    _need(
        set(index)
        == {"schema", "candidate_status", "source_bundle_member_count", "members", "lineage"}
        and index.get("schema") == "iteration41.optional16.r28.guard-facts.source-index.v1"
        and index.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and index.get("source_bundle_member_count") == 12,
        "r28_packet_index_schema_invalid",
    )
    member_hashes = _member_hashes(index.get("members"), 12, "r28_member_rows_invalid")
    _need(member_hashes == _r28_expected_member_hashes(), "r28_packet_members_invalid")
    _validate_zip(packet_raw, index["members"])

    expected_pin_keys = {
        "schema",
        "candidate_status",
        "acceptance",
        "case_pass",
        "registry_admission",
        "root_enabled",
        "root_profile_digest",
        "strict_cases_passed",
        "source_bundle_member_count",
        "sources",
        "reference_source_bundle_sha256",
        "reference_source_index_sha256",
        "reference_source_pins_sha256",
        "reference_review_verdict",
        "reference_review_json_sha256",
        "reference_review_bundle_sha256",
        "reference_actual_safe_summary_sha256",
        "fresh_paths",
        "qa",
        "execution_scope",
    }
    _need(
        set(pins) == expected_pin_keys
        and pins.get("schema") == "iteration41.optional16.r28.guard-facts.source-pins.v1"
        and pins.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and pins.get("acceptance") == "NOT_ESTABLISHED"
        and pins.get("case_pass") is False
        and pins.get("registry_admission") is False
        and pins.get("root_enabled") is False
        and pins.get("root_profile_digest") is None
        and _strict_zero(pins.get("strict_cases_passed"))
        and pins.get("source_bundle_member_count") == 12
        and pins.get("sources") == R28_SOURCE_PINS
        and pins.get("reference_source_bundle_sha256")
        == "d47d3be2c42b60eaf4a087653e7ea7967a96427367080e6514fcc4b5cde2c66b"
        and pins.get("reference_source_index_sha256")
        == "e8cf3b2abc6680e04531b02e00e74447ca337be23541d2cbed84bb9e910b17c5"
        and pins.get("reference_source_pins_sha256")
        == "4d692fb1a48310e6c8b12e132ddb716934d1edd5cd46e75fcfb45370d51b45fe"
        and pins.get("reference_review_verdict") == "GO_SOURCE_FAKE_ONLY"
        and pins.get("reference_review_json_sha256")
        == "e2a8e14a58583b3bce4190f2bd336547b215b6d804bda64f8a4592c9b0727a32"
        and pins.get("reference_review_bundle_sha256")
        == "a62ac90871141faec38b1a8837afff487ed9153629b8992a6b7554c066226e72"
        and pins.get("reference_actual_safe_summary_sha256")
        == "90917c3ba4b91f2a4464658ce8d0549cecb6d32f1eb7ca0fa514790f6d086ec5",
        "r28_packet_pins_schema_invalid",
    )

    expected_checkpoint_keys = {
        "schema",
        "created_on",
        "candidate_status",
        "acceptance",
        "case_pass",
        "registry_admission",
        "root_enabled",
        "strict_cases_passed",
        "source_bundle_sha256",
        "source_index_sha256",
        "source_pins_sha256",
        "source_bundle_member_count",
        "candidate_hashes",
    }
    _need(
        set(candidate_checkpoint) == expected_checkpoint_keys
        and candidate_checkpoint.get("schema")
        == "iteration41.optional16.r28.guard-facts.checkpoint.v1"
        and candidate_checkpoint.get("candidate_status") == pins["candidate_status"]
        and candidate_checkpoint.get("acceptance") == "NOT_ESTABLISHED"
        and candidate_checkpoint.get("case_pass") is False
        and candidate_checkpoint.get("registry_admission") is False
        and candidate_checkpoint.get("root_enabled") is False
        and _strict_zero(candidate_checkpoint.get("strict_cases_passed"))
        and candidate_checkpoint.get("source_bundle_member_count") == 12
        and candidate_checkpoint.get("source_bundle_sha256") == R28_PACKET_PINS["source-bundle.zip"]
        and candidate_checkpoint.get("source_index_sha256") == R28_PACKET_PINS["source-index.json"]
        and candidate_checkpoint.get("source_pins_sha256") == R28_PACKET_PINS["source-pins.json"]
        and candidate_checkpoint.get("candidate_hashes") == R28_SOURCE_PINS,
        "r28_candidate_checkpoint_schema_invalid",
    )

    expected_review_keys = {
        "candidate_packet",
        "candidate_status",
        "independent_verification",
        "integrity_checks",
        "limitations",
        "review_findings",
        "review_notes",
        "schema",
        "scope",
        "verdict",
    }
    reviewed_packet = review.get("candidate_packet")
    expected_review_packet_keys = {
        "checkpoint_sha256",
        "directory",
        "indexed_member_sha256",
        "member_count",
        "readme_sha256",
        "source_bundle_sha256",
        "source_index_sha256",
        "source_map_digest",
        "source_pins_sha256",
        "source_test_pins",
    }
    _need(
        set(review) == expected_review_keys
        and review.get("schema") == "iteration41.optional16.r28.independent-source-fake-review.v1"
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("candidate_status") == "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW"
        and review.get("review_findings") == []
        and type(reviewed_packet) is dict
        and set(reviewed_packet) == expected_review_packet_keys
        and reviewed_packet.get("checkpoint_sha256") == R28_PACKET_PINS["checkpoint.json"]
        and reviewed_packet.get("directory") == str(R28_PACKET.relative_to(ROOT)).replace("\\", "/")
        and reviewed_packet.get("indexed_member_sha256") == member_hashes
        and reviewed_packet.get("member_count") == 12
        and reviewed_packet.get("readme_sha256") == member_hashes["README.md"]
        and reviewed_packet.get("source_bundle_sha256") == R28_PACKET_PINS["source-bundle.zip"]
        and reviewed_packet.get("source_index_sha256") == R28_PACKET_PINS["source-index.json"]
        and reviewed_packet.get("source_pins_sha256") == R28_PACKET_PINS["source-pins.json"]
        and reviewed_packet.get("source_map_digest") is None
        and reviewed_packet.get("source_test_pins") == R28_SOURCE_PINS,
        "r28_review_schema_invalid",
    )

    expected_review_index_keys = {
        "member_count",
        "members",
        "review_bundle_sha256",
        "review_json_sha256",
        "schema",
        "verdict",
    }
    review_member_hashes = _member_hashes(
        review_index.get("members"), 7, "r28_review_member_rows_invalid"
    )
    _need(
        set(review_index) == expected_review_index_keys
        and review_index.get("schema") == "iteration41.optional16.r28.independent-review-index.v1"
        and review_index.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_index.get("member_count") == 7
        and review_index.get("review_json_sha256") == R28_REVIEW_PINS["review.json"]
        and review_index.get("review_bundle_sha256") == R28_REVIEW_PINS["review-bundle.zip"]
        and review_member_hashes == _r28_expected_review_member_hashes(),
        "r28_review_index_schema_invalid",
    )
    _validate_zip(review_archive, review_index["members"])

    expected_review_checkpoint_keys = {
        "acceptance",
        "candidate_checkpoint_sha256",
        "candidate_source_bundle_sha256",
        "candidate_source_index_sha256",
        "candidate_source_pins_sha256",
        "case_pass",
        "readme_sha256",
        "registry_admission",
        "review_bundle_member_count",
        "review_bundle_sha256",
        "review_index_sha256",
        "review_json_sha256",
        "schema",
        "strict_cases_passed",
        "verdict",
    }
    _need(
        set(review_checkpoint) == expected_review_checkpoint_keys
        and review_checkpoint.get("schema")
        == "iteration41.optional16.r28.independent-review-checkpoint.v1"
        and review_checkpoint.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_checkpoint.get("acceptance") == "NOT_ESTABLISHED"
        and review_checkpoint.get("case_pass") is False
        and review_checkpoint.get("registry_admission") is False
        and _strict_zero(review_checkpoint.get("strict_cases_passed"))
        and review_checkpoint.get("candidate_checkpoint_sha256")
        == R28_PACKET_PINS["checkpoint.json"]
        and review_checkpoint.get("candidate_source_bundle_sha256")
        == R28_PACKET_PINS["source-bundle.zip"]
        and review_checkpoint.get("candidate_source_index_sha256")
        == R28_PACKET_PINS["source-index.json"]
        and review_checkpoint.get("candidate_source_pins_sha256")
        == R28_PACKET_PINS["source-pins.json"]
        and review_checkpoint.get("readme_sha256")
        == _r28_expected_review_member_hashes()["README.md"]
        and review_checkpoint.get("review_bundle_member_count") == 7
        and review_checkpoint.get("review_bundle_sha256") == R28_REVIEW_PINS["review-bundle.zip"]
        and review_checkpoint.get("review_index_sha256") == R28_REVIEW_PINS["review-index.json"]
        and review_checkpoint.get("review_json_sha256") == R28_REVIEW_PINS["review.json"],
        "r28_review_checkpoint_schema_invalid",
    )

    for row in index["lineage"]:
        _need(
            type(row) is dict
            and set(row) == {"path", "relation", "sha256"}
            and type(row["path"]) is str
            and type(row["relation"]) is str
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]),
            "r28_lineage_row_invalid",
        )
        _need(
            _sha(_held(held, ROOT / Path(row["path"]))) == row["sha256"],
            "r28_lineage_digest_invalid",
        )

    _need(
        snapshot.get("status") == "CANDIDATE_FOR_ROOT_REVIEW_ONLY"
        and snapshot.get("sdk_imported") is False
        and snapshot.get("root_enabled") is False
        and snapshot.get("verified_distribution_count") == 6
        and snapshot.get("wheel_owned_hashed_payload_count") == 184
    )
    return snapshot


def _validate_driver_review(held):
    """Validate frozen R16/R17 and the exact R19 aggregate packet/review."""
    _need(_activation_ready(), "aggregate_successor_activation_fields_invalid")
    helper_raw = _held(held, ROOT_BINDING_HELPER)
    _need(_sha(helper_raw) == ROOT_BINDING_HELPER_SHA256, "aggregate_binding_helper_pin_mismatch")
    helper = _load_exact(
        helper_raw,
        ROOT_BINDING_HELPER,
        "_iteration41_optional16_r33_r19_aggregate_driver_binding",
        ROOT_BINDING_HELPER_SHA256,
    )
    source_names = {row["path"] for row in _r19_source_member_rows()}
    source_files = {name: _held(held, ROOT / name) for name in source_names}
    packet_files = {name: _held(held, DRIVER_PACKET / name) for name in ROOT_DRIVER_PACKET_PINS}
    review_files = {name: _held(held, DRIVER_REVIEW / name) for name in ROOT_DRIVER_REVIEW_PINS}
    r16_packet_files = {name: _held(held, R16_PACKET / name) for name in R16_PACKET_PINS}
    r16_review_files = {name: _held(held, R16_REVIEW / name) for name in R16_REVIEW_PINS}
    r17_packet_files = {name: _held(held, R17_PACKET / name) for name in R17_PACKET_PINS}
    r17_review_files = {name: _held(held, R17_REVIEW / name) for name in R17_REVIEW_PINS}
    r18_packet_files = {name: _held(held, R18_PACKET / name) for name in R18_PACKET_PINS}
    r18_review_files = {name: _held(held, R18_REVIEW / name) for name in R18_REVIEW_PINS}
    return helper.validate_successor_artifacts(
        source_files,
        packet_files,
        review_files,
        packet_pins=ROOT_DRIVER_PACKET_PINS,
        review_pins=ROOT_DRIVER_REVIEW_PINS,
        r16_packet_files=r16_packet_files,
        r16_review_files=r16_review_files,
        r17_packet_files=r17_packet_files,
        r17_review_files=r17_review_files,
        r18_packet_files=r18_packet_files,
        r18_review_files=r18_review_files,
    )


def _validate_r33_review(held, candidate_members):
    """Validate the exact source/fake review packet for the R33 candidate."""
    review_raw = _held(held, R33_REVIEW / "review.json")
    index_raw = _held(held, R33_REVIEW / "review-index.json")
    checkpoint_raw = _held(held, R33_REVIEW / "review-checkpoint.json")
    bundle_raw = _held(held, R33_REVIEW / "review-bundle.zip")
    _need(
        _sha(review_raw) == R33_REVIEW_PINS["review.json"]
        and _sha(index_raw) == R33_REVIEW_PINS["review-index.json"]
        and _sha(checkpoint_raw) == R33_REVIEW_PINS["review-checkpoint.json"]
        and _sha(bundle_raw) == R33_REVIEW_PINS["review-bundle.zip"],
        "r33_review_pin_mismatch",
    )
    review = json.loads(review_raw.decode("utf-8"))
    index = json.loads(index_raw.decode("utf-8"))
    checkpoint = json.loads(checkpoint_raw.decode("utf-8"))
    candidate = review.get("candidate")
    expected_candidate = {
        "candidate_sha256": R33_CANDIDATE_SHA256,
        "checkpoint_sha256": R33_PACKET_PINS["checkpoint.json"],
        "directory": R33_PACKET.name,
        "lineage_sha256": R33_PACKET_MEMBER_PINS["lineage.json"],
        "member_count": 30,
        "qa_summary_sha256": R33_PACKET_MEMBER_PINS["qa-summary.json"],
        "readme_sha256": R33_PACKET_MEMBER_PINS["README.md"],
        "source_bundle_sha256": R33_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R33_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R33_PACKET_PINS["source-pins.json"],
        "test_sha256": R33_TEST_SHA256,
    }
    _need(
        type(review) is dict
        and set(review)
        == {
            "acceptance",
            "candidate",
            "case_pass",
            "classification",
            "decision",
            "nonblocking_note",
            "registry_admission",
            "reviewed_input",
            "schema",
            "scope_limitations",
            "source_fake_checks",
            "strict_cases_passed",
            "verdict",
        }
        and review.get("schema")
        == "iteration41.optional16.installed-matrix-r33.independent-source-fake-review.v1"
        and review.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("classification") == "SOURCE_FAKE_ONLY_NOT_ACTUAL"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and _strict_zero(review.get("strict_cases_passed"))
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and candidate == expected_candidate,
        "r33_review_contract_invalid",
    )
    reviewed_input = review.get("reviewed_input")
    _need(
        type(reviewed_input) is dict
        and set(reviewed_input)
        == {
            "active_candidate_and_test_match_frozen_hashes",
            "all_indexed_archive_members_verified",
            "source_index_schema",
            "unique_zip_names",
            "workspace_candidate_sha256",
            "workspace_test_sha256",
            "zip_crc_check_passed",
        }
        and reviewed_input.get("active_candidate_and_test_match_frozen_hashes") is True
        and reviewed_input.get("all_indexed_archive_members_verified") is True
        and reviewed_input.get("source_index_schema") == R33_SOURCE_INDEX_SCHEMA
        and reviewed_input.get("unique_zip_names") is True
        and reviewed_input.get("workspace_candidate_sha256") == R33_CANDIDATE_SHA256
        and reviewed_input.get("workspace_test_sha256") == R33_TEST_SHA256
        and reviewed_input.get("zip_crc_check_passed") is True,
        "r33_reviewed_input_invalid",
    )
    checks = review.get("source_fake_checks")
    matrix_check = checks.get("full_sixteen_case_matrix") if type(checks) is dict else None
    diagnostic_check = checks.get("r33_diagnostic_trace") if type(checks) is dict else None
    _need(
        type(checks) is dict
        and set(checks) == {"activation", "full_sixteen_case_matrix", "r33_diagnostic_trace"}
        and checks.get("activation")
        == {
            "registry_admission": False,
            "root_enabled": False,
            "root_profile_digest": None,
        }
        and type(matrix_check) is dict
        and matrix_check.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and matrix_check.get("fake_provider_and_in_memory_zmq_only") is True
        and matrix_check.get("fake_sdk_shaped_modules_and_factories") is True
        and matrix_check.get("frozen_r28_matrix_executed") is True
        and matrix_check.get("projected_status") == "LOCAL_DIAGNOSTIC_ONLY"
        and _strict_zero(matrix_check.get("strict_cases_passed"))
        and matrix_check.get("transport_feature_combinations") == 16
        and matrix_check.get("valid_r28_output_accepted_by_r33") is True,
        "r33_review_matrix_check_invalid",
    )
    _need(
        type(diagnostic_check) is dict
        and set(diagnostic_check)
        == {
            "diagnostic_test_sha256",
            "dispatch_exception_exits_verified_import_scope",
            "fixed_marker_on_first_matrix_trace_write_failure",
            "matrix_operation_continues_after_trace_failure",
            "phase_prefix_separates_matrix_import_scope_guard_dispatch",
        }
        and diagnostic_check.get("diagnostic_test_sha256") == R33_DIAGNOSTIC_TEST_SHA256
        and diagnostic_check.get("dispatch_exception_exits_verified_import_scope") is True
        and diagnostic_check.get("fixed_marker_on_first_matrix_trace_write_failure") is True
        and diagnostic_check.get("matrix_operation_continues_after_trace_failure") is True
        and diagnostic_check.get("phase_prefix_separates_matrix_import_scope_guard_dispatch")
        is True,
        "r33_review_diagnostic_trace_invalid",
    )
    _need(
        set(index)
        == {
            "candidate_checkpoint_sha256",
            "candidate_source_bundle_sha256",
            "candidate_source_index_sha256",
            "candidate_source_pins_sha256",
            "decision",
            "members",
            "review_bundle_sha256",
            "review_json_sha256",
            "schema",
        }
        and index.get("schema")
        == "iteration41.optional16.installed-matrix-r33.independent-review-index.v1"
        and index.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and index.get("candidate_checkpoint_sha256") == R33_PACKET_PINS["checkpoint.json"]
        and index.get("candidate_source_bundle_sha256") == R33_PACKET_PINS["source-bundle.zip"]
        and index.get("candidate_source_index_sha256") == R33_PACKET_PINS["source-index.json"]
        and index.get("candidate_source_pins_sha256") == R33_PACKET_PINS["source-pins.json"]
        and index.get("review_bundle_sha256") == R33_REVIEW_PINS["review-bundle.zip"]
        and index.get("review_json_sha256") == R33_REVIEW_PINS["review.json"],
        "r33_review_index_invalid",
    )
    review_members = index.get("members")
    expected_review_rows = [
        {
            "bytes": 1557,
            "path": "README.md",
            "sha256": R33_REVIEW_README_SHA256,
        },
        {
            "bytes": 1756,
            "path": "qa-summary.json",
            "sha256": "ac1d41238c3089f23962028550ec2e58212583d9ba2753507e4d80db6dc448c9",
        },
        {
            "bytes": 3574,
            "path": "review.json",
            "sha256": R33_REVIEW_PINS["review.json"],
        },
    ]
    _need(
        type(review_members) is list and review_members == expected_review_rows,
        "r33_review_member_index_invalid",
    )
    review_rows_by_path = {row["path"]: row for row in review_members}
    review_contents = _validate_zip(
        bundle_raw,
        [review_rows_by_path[path] for path in ("README.md", "review.json", "qa-summary.json")],
    )
    _need(
        review_contents.get("review.json") == review_raw,
        "r33_review_bundle_json_mismatch",
    )
    review_readme = _held(held, R33_REVIEW / "README.md")
    _need(
        review_contents.get("README.md") == review_readme
        and _sha(review_readme) == R33_REVIEW_README_SHA256,
        "r33_review_bundle_readme_mismatch",
    )
    qa_raw = review_contents.get("qa-summary.json")
    try:
        qa = json.loads(qa_raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        _need(False, "r33_review_qa_summary_invalid")
    expected_qa = {
        "actual_sdk_or_provider_run": False,
        "black_py311_check_passed": False,
        "black_reformat_paths": [
            "backtrader_runtime/certification_optional16_installed_matrix_r33_candidate.py"
        ],
        "candidate_sha256": R33_CANDIDATE_SHA256,
        "case_pass": False,
        "diagnostic_test_sha256": R33_DIAGNOSTIC_TEST_SHA256,
        "environment_file_accessed": False,
        "focused_test_command": (
            "python -B -m pytest tests/unit/runtime/"
            "test_certification_optional16_installed_matrix_r33_source_fake.py "
            "tests/unit/runtime/test_certification_optional16_installed_matrix_r33_diagnostics.py "
            "-q -p no:cacheprovider -p no:asyncio --tb=short"
        ),
        "focused_test_count": 27,
        "focused_tests_passed": 27,
        "in_memory_compile_passed": True,
        "initial_default_plugin_collection_issue": (
            "pytest-asyncio collection failed before tests with AttributeError: "
            "Package has no attribute obj; neither focused test file defines async tests."
        ),
        "main_test_sha256": R33_TEST_SHA256,
        "native_module_accessed": False,
        "network_accessed": False,
        "private_configuration_accessed": False,
        "pytest_asyncio_disabled_for_rerun": True,
        "pytest_config_warning": "Unknown config option: asyncio_default_fixture_loop_scope",
        "registry_admission": False,
        "review_bundle_rows": ["README.md", "review.json", "qa-summary.json"],
        "ruff_check_passed": True,
        "schema": "iteration41.optional16.r33.independent-review-qa.v1",
        "source_bundle_sha256": R33_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R33_PACKET_PINS["source-index.json"],
        "strict_cases_passed": 0,
    }
    _need(type(qa) is dict and qa == expected_qa, "r33_review_qa_summary_contract_invalid")
    _need(
        set(checkpoint)
        == {
            "candidate_checkpoint_sha256",
            "candidate_source_bundle_sha256",
            "candidate_source_index_sha256",
            "candidate_source_pins_sha256",
            "decision",
            "member_count",
            "review_bundle_sha256",
            "review_index_sha256",
            "review_json_sha256",
            "schema",
        }
        and checkpoint.get("schema")
        == "iteration41.optional16.installed-matrix-r33.independent-review-checkpoint.v1"
        and checkpoint.get("decision") == "GO_SOURCE_FAKE_ONLY"
        and checkpoint.get("candidate_checkpoint_sha256") == R33_PACKET_PINS["checkpoint.json"]
        and checkpoint.get("candidate_source_bundle_sha256") == R33_PACKET_PINS["source-bundle.zip"]
        and checkpoint.get("candidate_source_index_sha256") == R33_PACKET_PINS["source-index.json"]
        and checkpoint.get("candidate_source_pins_sha256") == R33_PACKET_PINS["source-pins.json"]
        and checkpoint.get("member_count") == 3
        and checkpoint.get("review_bundle_sha256") == R33_REVIEW_PINS["review-bundle.zip"]
        and checkpoint.get("review_index_sha256") == R33_REVIEW_PINS["review-index.json"]
        and checkpoint.get("review_json_sha256") == R33_REVIEW_PINS["review.json"],
        "r33_review_checkpoint_invalid",
    )
    return review


def _validate_r33_candidate_review(held):
    """Validate all R33 source bytes, the packet archive, and independent review."""
    source_index_raw = _held(held, R33_PACKET / "source-index.json")
    source_pins_raw = _held(held, R33_PACKET / "source-pins.json")
    checkpoint_raw = _held(held, R33_PACKET / "checkpoint.json")
    bundle_raw = _held(held, R33_PACKET / "source-bundle.zip")
    _need(
        _sha(source_index_raw) == R33_PACKET_PINS["source-index.json"]
        and _sha(source_pins_raw) == R33_PACKET_PINS["source-pins.json"]
        and _sha(checkpoint_raw) == R33_PACKET_PINS["checkpoint.json"]
        and _sha(bundle_raw) == R33_PACKET_PINS["source-bundle.zip"],
        "r33_source_packet_pin_mismatch",
    )
    index = json.loads(source_index_raw.decode("utf-8"))
    pins = json.loads(source_pins_raw.decode("utf-8"))
    checkpoint = json.loads(checkpoint_raw.decode("utf-8"))
    rows = index.get("members")
    _need(
        set(index) == {"candidate_schema", "member_count", "members", "schema"}
        and index.get("schema") == R33_SOURCE_INDEX_SCHEMA
        and index.get("candidate_schema") == "iteration41.optional16.installed-matrix-r33.v1"
        and index.get("member_count") == 30
        and type(rows) is list
        and len(rows) == 30,
        "r33_source_index_invalid",
    )
    normalized_rows = []
    row_by_path = {}
    for row in rows:
        _need(
            type(row) is dict
            and set(row) == {"bytes", "path", "role", "sha256"}
            and type(row["path"]) is str
            and type(row["role"]) is str
            and type(row["bytes"]) is int
            and row["bytes"] >= 0
            and type(row["sha256"]) is str
            and _HASH.fullmatch(row["sha256"]),
            "r33_source_member_invalid",
        )
        _need(row["path"] not in row_by_path, "r33_source_member_duplicate")
        row_by_path[row["path"]] = row
        normalized_rows.append({key: row[key] for key in ("path", "bytes", "sha256")})
    members = _validate_zip(bundle_raw, normalized_rows)
    expected_sources = {
        "backtrader_runtime/certification_optional16_installed_matrix_r33_candidate.py": R33_CANDIDATE_SHA256,
        "tests/unit/runtime/test_certification_optional16_installed_matrix_r33_source_fake.py": R33_TEST_SHA256,
        "tests/unit/runtime/test_certification_optional16_installed_matrix_r33_diagnostics.py": R33_DIAGNOSTIC_TEST_SHA256,
    }
    for path, digest in expected_sources.items():
        _need(
            path in members
            and _sha(members[path]) == digest
            and _sha(_held(held, ROOT / path)) == digest,
            "r33_active_source_mismatch",
        )
    expected_pins = {
        "schema": R33_SOURCE_PINS_SCHEMA,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "candidate_sha256": R33_CANDIDATE_SHA256,
        "case_pass": False,
        "diagnostic_test_sha256": R33_DIAGNOSTIC_TEST_SHA256,
        "focused_test_sha256": R33_TEST_SHA256,
        "member_count": 30,
        "previous_r32_candidate_sha256": "a55a77bd16d65853fac03cbc689159fd66fc4f526b20ce68e9e396fe48d20c0f",
        "previous_r32_test_sha256": "c87fcecd69c43638d05f5f348203dc72f568c0583cacdde54e253cb16c5eb9ae",
        "registry_admission": False,
        "root_enabled": False,
        "root_profile_digest": None,
        "source_bundle_sha256": R33_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R33_PACKET_PINS["source-index.json"],
        "strict_cases_passed": 0,
    }
    _need(pins == expected_pins, "r33_source_pins_invalid")
    expected_checkpoint = {
        "schema": R33_SOURCE_CHECKPOINT_SCHEMA,
        "status": "SOURCE_FAKE_ONLY_READY_FOR_INDEPENDENT_REVIEW",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "actual_sdk_or_provider_run": False,
        "candidate_sha256": R33_CANDIDATE_SHA256,
        "case_pass": False,
        "diagnostic_test_sha256": R33_DIAGNOSTIC_TEST_SHA256,
        "focused_test_sha256": R33_TEST_SHA256,
        "lineage_sha256": R33_PACKET_MEMBER_PINS["lineage.json"],
        "qa_summary_sha256": R33_PACKET_MEMBER_PINS["qa-summary.json"],
        "readme_sha256": R33_PACKET_MEMBER_PINS["README.md"],
        "registry_admission": False,
        "root_enabled": False,
        "root_profile_digest": None,
        "source_bundle_sha256": R33_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R33_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R33_PACKET_PINS["source-pins.json"],
        "strict_cases_passed": 0,
    }
    _need(
        type(checkpoint) is dict and checkpoint == expected_checkpoint,
        "r33_source_checkpoint_invalid",
    )
    for member_name, digest in R33_PACKET_MEMBER_PINS.items():
        _need(
            member_name in members and _sha(members[member_name]) == digest,
            "r33_source_archive_member_pin_invalid",
        )
    review = _validate_r33_review(held, members)
    return review


def _build_child_source(candidate_source, snapshot_source, progress_path):
    _need(
        type(candidate_source) is bytes and _sha(candidate_source) == R33_CANDIDATE_SHA256,
        "r33_candidate_source_mismatch",
    )
    _need(
        type(snapshot_source) is bytes and _sha(snapshot_source) == SNAPSHOT_SHA256,
        "r25_snapshot_source_mismatch",
    )
    lines = [
        "import hashlib,importlib.machinery,json,pathlib,sys,types",
        "raw=bytes.fromhex(" + repr(candidate_source.hex()) + ")",
        "snapshot_raw=bytes.fromhex(" + repr(snapshot_source.hex()) + ")",
        "assert hashlib.sha256(raw).hexdigest()==" + repr(R33_CANDIDATE_SHA256),
        "assert hashlib.sha256(snapshot_raw).hexdigest()==" + repr(SNAPSHOT_SHA256),
        "name='_iteration41_optional16_r33_matrix_child'",
        "assert name not in sys.modules",
        "module=types.ModuleType(name)",
        "module.__file__=" + repr(str(R33_CANDIDATE)),
        "module.__package__=''",
        "module.__cached__=None",
        "module.__loader__=None",
        "module.__spec__=importlib.machinery.ModuleSpec(name,loader=None,origin=module.__file__)",
        "module.__verified_source_sha256__=hashlib.sha256(raw).hexdigest()",
        "sys.modules[name]=module",
        "exec(compile(raw,module.__file__,'exec',dont_inherit=True),module.__dict__)",
        "assert module.ROOT_ENABLED is False and module.ROOT_PROFILE_DIGEST is None",
        "snapshot=json.loads(snapshot_raw.decode('utf-8'))",
        "assert type(snapshot) is dict and snapshot.get('schema')=='iteration41.optional16.r25.installed-record-candidate.v1'",
        "assert snapshot.get('status')=='CANDIDATE_FOR_ROOT_REVIEW_ONLY'",
        "assert type(snapshot.get('strict_cases_passed')) is int and snapshot.get('strict_cases_passed')==0",
        "assert snapshot.get('acceptance')=='NOT_ESTABLISHED' and snapshot.get('case_pass') is False and snapshot.get('registry_admission') is False",
        "assert snapshot.get('root_enabled') is False and snapshot.get('root_profile_digest') is None",
        "assert snapshot.get('installed_record_snapshots_bound') is False and snapshot.get('sdk_imported') is False",
        "assert snapshot.get('provider_requests') is False and snapshot.get('private_inputs_read') is False",
        "rows=snapshot.get('distributions')",
        "assert type(rows) is list and len(rows)==6",
        "expected_names=('bt_api_base','bt_api_execution','bt_api_gateway','bt_api_monitor','bt_api_risk','bt_api_transport_zmq')",
        "snapshots=[]",
        "for index,row in enumerate(rows):",
        "    assert type(row) is dict and set(row)=={'distribution','version','installed_record_sha256','installed_record_rows','wheel_owned_hashed_payloads_verified','generated_rows'}",
        "    assert row['distribution']==expected_names[index] and type(row['version']) is str",
        "    assert type(row['installed_record_sha256']) is str and len(row['installed_record_sha256'])==64",
        "    assert type(row['installed_record_rows']) is int and row['installed_record_rows']>0",
        "    assert type(row['wheel_owned_hashed_payloads_verified']) is int and row['wheel_owned_hashed_payloads_verified']>=0",
        "    generated=row.get('generated_rows')",
        "    assert type(generated) is list and all(type(item) is dict and set(item)=={'kind','path','record_hash','size_text'} and all(type(item[key]) is str for key in ('kind','path','record_hash','size_text')) for item in generated)",
        "    generated_rows=tuple(module.GeneratedRecordRow(item['kind'],item['path'],item['record_hash'],item['size_text']) for item in generated)",
        "    snapshots.append(module.InstalledRecordSnapshot(row['distribution'],row['version'],row['installed_record_sha256'],row['installed_record_rows'],generated_rows))",
        "module.R25_INSTALLED_RECORD_SNAPSHOTS=tuple(snapshots)",
        "module.ROOT_ENABLED=True",
        "module.ROOT_PROFILE_DIGEST=" + repr(R33_PACKET_PINS["source-bundle.zip"]),
        "module.MATRIX_PARENT=pathlib.Path(" + repr(str(SCRATCH)) + ")",
        "_progress_path=pathlib.Path(" + repr(str(progress_path)) + ")",
        "_old_stderr=sys.stderr",
        "class _R5ProgressTee:",
        "    def __init__(self, original, path):",
        "        self._original=original",
        "        self._file=None",
        "        self._failed=False",
        "        self._frames=0",
        "        self._bytes=0",
        "        try:",
        "            handle=open(path,'r+b',buffering=0)",
        "            if handle.read(len("
        + repr(PROGRESS_PENDING)
        + "))!="
        + repr(PROGRESS_PENDING)
        + ":",
        "                raise OSError('sidecar_header')",
        "            handle.seek(0)",
        "            if handle.write("
        + repr(PROGRESS_OPENED)
        + ")!=len("
        + repr(PROGRESS_OPENED)
        + "):",
        "                raise OSError('sidecar_open_marker')",
        "            handle.flush()",
        "            handle.seek(0,2)",
        "            if handle.tell()!=len(" + repr(PROGRESS_PENDING) + "):",
        "                raise OSError('sidecar_initial_size')",
        "            self._file=handle",
        "        except BaseException:",
        "            self._failed=True",
        "            try: handle.close()",
        "            except BaseException: pass",
        "    @property",
        "    def buffer(self): return self",
        "    def write(self, data):",
        "        written=self._original.write(data)",
        "        if type(data) is bytes and (data.startswith(b'R26PHASE') or data.startswith(b'R28MATRIX') or data.startswith(b'R26DIAG|')):",
        "            try: self._mirror(data)",
        "            except BaseException: self._mark_failed()",
        "        return written",
        "    def _mirror(self, data):",
        "        if self._failed or self._file is None: return",
        "        if (not data.endswith(b'\\n') or data.count(b'\\n')!=1 or b'\\r' in data or len(data)>160):",
        "            raise OSError('sidecar_frame_shape')",
        "        if data == " + repr(_TRACE_START_FAILURE_FRAME) + ":",
        "            fields=None",
        "        elif data.startswith(b'R26DIAG|'):",
        "            raise OSError('diagnostic_marker')",
        "        elif data.startswith(b'R26PHASE|'):",
        "            fields=data[:-1].decode('ascii').split('|')",
        "            if len(fields)!=4: raise OSError('phase_shape')",
        "        elif data.startswith(b'R28MATRIX|'):",
        "            fields=data[:-1].decode('ascii').split('|')",
        "            if len(fields)!=7: raise OSError('matrix_shape')",
        "        else: raise OSError('frame_prefix')",
        "        if self._frames>=697 or self._bytes+len(data)>73728+len("
        + repr(_TRACE_START_FAILURE_FRAME)
        + "): raise OSError('sidecar_limit')",
        "        if self._file.write(data)!=len(data): raise OSError('sidecar_write')",
        "        self._file.flush()",
        "        self._frames+=1; self._bytes+=len(data)",
        "    def _mark_failed(self):",
        "        self._failed=True",
        "        if self._file is not None:",
        "            try:",
        "                self._file.seek(0)",
        "                self._file.write(" + repr(PROGRESS_FAILED) + ")",
        "                self._file.flush()",
        "            except BaseException: pass",
        "    def finish(self):",
        "        if self._file is None: return",
        "        try:",
        "            self._file.seek(0)",
        "            marker="
        + repr(PROGRESS_FAILED)
        + " if self._failed else "
        + repr(PROGRESS_COMPLETE),
        "            if self._file.write(marker)!=len(marker): raise OSError('sidecar_marker')",
        "            self._file.flush()",
        "        except BaseException: self._mark_failed()",
        "        try: self._file.close()",
        "        except BaseException: self._mark_failed()",
        "    def flush(self):",
        "        self._original.flush()",
        "        if self._file is not None and not self._failed:",
        "            try: self._file.flush()",
        "            except BaseException: self._mark_failed()",
        "    def writelines(self, lines):",
        "        for line in lines: self.write(line)",
        "    def isatty(self): return False",
        "class _R5StderrProxy:",
        "    def __init__(self, original, tee): self._original=original; self.buffer=tee",
        "    def write(self, value): return self._original.write(value)",
        "    def flush(self): return self.buffer.flush()",
        "    def isatty(self): return False",
        "_tee=_R5ProgressTee(_old_stderr.buffer,_progress_path)",
        "sys.stderr=_R5StderrProxy(_old_stderr,_tee)",
        "try:",
        "    report=module.run_current_invocation()",
        "except BaseException:",
        "    report=module._blocked('r33_child_entry_failed')",
        "finally:",
        "    _tee.finish()",
        "    sys.stderr=_old_stderr",
        "assert type(report) is dict",
        "body=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')",
        "sys.stdout.buffer.write(b'R33MATRIXFINAL|'+body+b'\\n')",
        "sys.stdout.buffer.flush()",
        "raise SystemExit(0 if report.get('status')=='LOCAL_DIAGNOSTIC_ONLY' else 2)",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


_PROGRESS_UNAVAILABLE_REASONS = frozenset(
    {
        "sidecar_header_invalid",
        "sidecar_limit_exceeded",
        "sidecar_readback_invalid",
        "sidecar_writer_failed",
        "sidecar_not_started",
        "sidecar_completion_missing",
        "phase_frame_invalid",
        "matrix_frame_invalid",
        "matrix_outside_matrix_dispatch",
        "matrix_trace_start_failed",
    }
)


def _unavailable_progress(reason):
    if reason not in _PROGRESS_UNAVAILABLE_REASONS:
        reason = "sidecar_readback_invalid"
    return {
        "schema": "iteration41.optional16.r33.progress-diagnostic.r5.v1",
        "availability": "UNAVAILABLE",
        "reason_code": reason,
        "capture_state": "UNAVAILABLE",
        "phase_status": "UNAVAILABLE",
        "phase_event_count": None,
        "last_phase": None,
        "active_phase": None,
        "matrix_status": "UNAVAILABLE",
        "matrix_frame_count": None,
        "completed_case_count": None,
        "last_case_id": None,
        "active_stage": None,
        "last_elapsed_ms": None,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ESTABLISHED",
        "authority": "DIAGNOSTIC_ONLY",
    }


def _parse_phase_progress(data, candidate_module):
    if (
        type(data) is not bytes
        or len(data) > 8192
        or (data and not data.endswith(b"\n"))
        or b"\r" in data
    ):
        raise ValueError("phase framing")
    names = candidate_module._PHASE_NAMES
    cleanup_names = candidate_module._PHASE_CLEANUP_NAMES
    expected = candidate_module._PHASE_FIRST_ORDINAL
    frames = 0
    last_index = -1
    current = None
    failed = False
    last_phase = None
    for raw_line in data.splitlines():
        fields = raw_line.decode("ascii").split("|")
        if (
            len(fields) != 4
            or fields[0] != "R26PHASE"
            or not fields[1].isascii()
            or not fields[1].isdecimal()
            or str(int(fields[1])) != fields[1]
            or int(fields[1]) != expected
            or fields[2] not in names
            or fields[3] not in {"B", "E", "F"}
            or frames >= 56
        ):
            raise ValueError("phase frame")
        expected += 1
        frames += 1
        phase = fields[2]
        event = fields[3]
        index = names.index(phase)
        if event == "B":
            if (
                current is not None
                or index <= last_index
                or (failed and phase not in cleanup_names)
            ):
                raise ValueError("phase order")
            current = phase
            last_index = index
        else:
            if current != phase:
                raise ValueError("phase pair")
            current = None
            failed = failed or event == "F"
        last_phase = phase
    if current is not None:
        status = "IN_PROGRESS"
    elif failed:
        status = "FAILED_DIAGNOSTIC"
    elif frames == 0:
        status = "NOT_STARTED"
    elif last_phase == "result_ready" and not failed:
        status = "COMPLETE_DIAGNOSTIC"
    else:
        status = "PREFIX"
    return {
        "status": status,
        "frame_count": frames,
        "last_phase": last_phase,
        "active_phase": current,
    }


def _parse_progress_sidecar(raw, candidate_module, *, timed_out):
    if type(raw) is not bytes or len(raw) > PROGRESS_MAX_BYTES:
        return _unavailable_progress("sidecar_limit_exceeded")
    header_len = len(PROGRESS_PENDING)
    if len(raw) < header_len or raw[: len(PROGRESS_HEADER_PREFIX)] != PROGRESS_HEADER_PREFIX:
        return _unavailable_progress("sidecar_header_invalid")
    header = raw[:header_len]
    frames = raw[header_len:]
    if header == PROGRESS_FAILED:
        return _unavailable_progress("sidecar_writer_failed")
    if header == PROGRESS_PENDING:
        return _unavailable_progress("sidecar_not_started")
    if header not in {PROGRESS_OPENED, PROGRESS_COMPLETE}:
        return _unavailable_progress("sidecar_header_invalid")
    capture_state = "COMPLETE" if header == PROGRESS_COMPLETE else "PREFIX"
    if header == PROGRESS_OPENED and timed_out is not True:
        return _unavailable_progress("sidecar_completion_missing")
    phase_frames = bytearray()
    matrix_frames = bytearray()
    try:
        if frames and (not frames.endswith(b"\n") or b"\r" in frames):
            raise ValueError("truncated frame")
        if frames.count(b"\n") > 697 or len(frames) > PROGRESS_FOOTERLESS_LIMIT:
            raise OverflowError("frame limit")
        phase_open = None
        matrix_started = False
        trace_start_failed = False
        for raw_line in frames.splitlines(keepends=True):
            if raw_line.startswith(b"R26PHASE|"):
                fields = raw_line[:-1].decode("ascii").split("|")
                if len(fields) != 4:
                    raise ValueError("phase shape")
                phase_frames.extend(raw_line)
                if fields[3] == "B":
                    phase_open = fields[2]
                elif phase_open == fields[2] and fields[3] in {"E", "F"}:
                    phase_open = None
                elif fields[3] in {"E", "F"}:
                    raise ValueError("phase pair")
                if fields[2] == "matrix_dispatch" and fields[3] == "B":
                    matrix_started = True
                elif fields[2] == "matrix_dispatch" and fields[3] in {"E", "F"}:
                    matrix_started = False
            elif raw_line == _TRACE_START_FAILURE_FRAME:
                if (
                    trace_start_failed
                    or not matrix_started
                    or phase_open != "matrix_dispatch"
                    or matrix_frames
                ):
                    raise ValueError("trace start marker boundary")
                trace_start_failed = True
            elif raw_line.startswith(b"R26DIAG"):
                raise ValueError("trace marker invalid")
            elif raw_line.startswith(b"R28MATRIX|"):
                if trace_start_failed:
                    matrix_frames.extend(raw_line)
                    raise ValueError("matrix frame after trace start marker")
                if not matrix_started or phase_open != "matrix_dispatch":
                    raise LookupError("matrix boundary")
                matrix_frames.extend(raw_line)
            else:
                raise ValueError("unknown frame")
        phase = _parse_phase_progress(bytes(phase_frames), candidate_module)
        if trace_start_failed:
            if matrix_frames:
                raise ValueError("trace start marker with matrix frames")
            return {
                "schema": "iteration41.optional16.r33.progress-diagnostic.r5.v1",
                "availability": "AVAILABLE",
                "reason_code": "matrix_trace_start_failed",
                "capture_state": capture_state,
                "phase_status": phase["status"],
                "phase_event_count": phase["frame_count"],
                "last_phase": phase["last_phase"],
                "active_phase": phase["active_phase"],
                "matrix_status": "UNAVAILABLE",
                "matrix_frame_count": 0,
                "completed_case_count": None,
                "last_case_id": None,
                "active_stage": None,
                "last_elapsed_ms": None,
                "strict_cases_passed": 0,
                "case_pass": False,
                "acceptance": "NOT_ESTABLISHED",
                "authority": "DIAGNOSTIC_ONLY",
            }
        matrix = candidate_module.parse_matrix_progress_frames(bytes(matrix_frames))
        if matrix_frames and matrix.get("frame_count") == 0:
            raise ValueError("matrix parse empty")
        return {
            "schema": "iteration41.optional16.r33.progress-diagnostic.r5.v1",
            "availability": "AVAILABLE",
            "reason_code": None,
            "capture_state": capture_state,
            "phase_status": phase["status"],
            "phase_event_count": phase["frame_count"],
            "last_phase": phase["last_phase"],
            "active_phase": phase["active_phase"],
            "matrix_status": matrix["status"],
            "matrix_frame_count": matrix["frame_count"],
            "completed_case_count": matrix["completed_case_count"],
            "last_case_id": matrix["last_case_id"],
            "active_stage": matrix["active_stage"],
            "last_elapsed_ms": matrix["last_elapsed_ms"],
            "strict_cases_passed": 0,
            "case_pass": False,
            "acceptance": "NOT_ESTABLISHED",
            "authority": "DIAGNOSTIC_ONLY",
        }
    except LookupError:
        return _unavailable_progress("matrix_outside_matrix_dispatch")
    except OverflowError:
        return _unavailable_progress("sidecar_limit_exceeded")
    except BaseException:
        return _unavailable_progress(
            "phase_frame_invalid" if not matrix_frames else "matrix_frame_invalid"
        )


def _open_progress_lease(control, private):
    control.write_bytes(PROGRESS_NAME, PROGRESS_PENDING)
    api = private._api()
    sid = api.current_sid()
    context = api.opened(PROGRESS_PATH, directory=False, access=0x80020080)
    handle = context.__enter__()
    try:
        identity = api.info(handle, directory=False)
        api.verify_acl(handle, sid)
        return {
            "context": context,
            "handle": handle,
            "identity": identity,
            "api": api,
            "sid": sid,
            "path": PROGRESS_PATH,
            "closed": False,
        }
    except BaseException:
        context.__exit__(*sys.exc_info())
        raise


def _read_progress_after_postverify(progress_lease, private, cli, candidate_module, *, timed_out):
    api = progress_lease["api"]
    handle = progress_lease["handle"]
    sid = progress_lease["sid"]
    identity = progress_lease["identity"]
    _need(api.info(handle, directory=False) == identity, "progress_identity_changed")
    api.verify_acl(handle, sid)
    with cli._locked_readonly_file(progress_lease["path"], private, api) as read_lease:
        read_handle, read_identity = read_lease
        _need(read_identity == identity, "progress_read_identity_changed")
        api.verify_acl(read_handle, sid)
        raw = cli._read_bounded_handle(api, read_handle, PROGRESS_MAX_BYTES)
        _need(api.info(read_handle, directory=False) == identity, "progress_read_identity_changed")
    _need(api.info(handle, directory=False) == identity, "progress_identity_changed")
    api.verify_acl(handle, sid)
    return _parse_progress_sidecar(raw, candidate_module, timed_out=timed_out)


def _close_progress_lease(progress_lease):
    if progress_lease is None or progress_lease.get("closed") is True:
        return
    progress_lease["context"].__exit__(None, None, None)
    progress_lease["closed"] = True


def _candidate_parser(held):
    raw = _held(held, R33_CANDIDATE)
    name = "_iteration41_optional16_r33_root_parser"
    module = types.ModuleType(name)
    module.__file__ = str(R33_CANDIDATE)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=module.__file__)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


def _parse_final(raw, candidate_module=None):
    _need(
        type(raw) is bytes
        and 0 < len(raw) <= MAX_RESULT_BYTES
        and raw.startswith(_FINAL_PREFIX)
        and raw.endswith(b"\n")
        and b"\r" not in raw
        and raw.count(b"\n") == 1,
        "r33_final_frame_invalid",
    )
    body = raw[len(_FINAL_PREFIX) : -1]
    try:
        report = json.loads(body.decode("utf-8"))
    except Exception:
        raise RuntimeError("r33_final_json_invalid") from None
    _need(
        type(report) is dict
        and _canonical(report) == body
        and report.get("schema") == "iteration41.optional16.installed-matrix-r33.v1"
        and _strict_zero(report.get("strict_cases_passed"))
        and report.get("case_pass") is False
        and report.get("registry_admission") is False,
        "r33_final_contract_invalid",
    )
    if report.get("status") == "BLOCKED":
        _need(
            set(report)
            == {
                "schema",
                "status",
                "reason",
                "acceptance",
                "case_pass",
                "registry_admission",
                "strict_cases_passed",
            }
            and report.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
            and type(report.get("reason")) is str
            and re.fullmatch(r"[a-z0-9_]{1,96}", report["reason"]) is not None,
            "r33_blocked_frame_invalid",
        )
        return report
    expected_ids = (
        "D-E0-R0-M0",
        "D-E0-R0-M1",
        "D-E0-R1-M0",
        "D-E0-R1-M1",
        "D-E1-R0-M0",
        "D-E1-R0-M1",
        "D-E1-R1-M0",
        "D-E1-R1-M1",
        "GZ-E0-R0-M0",
        "GZ-E0-R0-M1",
        "GZ-E0-R1-M0",
        "GZ-E0-R1-M1",
        "GZ-E1-R0-M0",
        "GZ-E1-R0-M1",
        "GZ-E1-R1-M0",
        "GZ-E1-R1-M1",
    )
    _need(
        set(report)
        == {
            "schema",
            "status",
            "acceptance",
            "case_pass",
            "registry_admission",
            "strict_cases_passed",
            "provider_session_created",
            "network_access_allowed",
            "case_count",
            "results",
            "transport_cleanup_complete",
            "source_scope",
        }
        and report.get("status") == "LOCAL_DIAGNOSTIC_ONLY"
        and report.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and report.get("provider_session_created") is False
        and report.get("network_access_allowed") is False
        and type(report.get("case_count")) is int
        and report["case_count"] == 16
        and report.get("transport_cleanup_complete") is True
        and report.get("source_scope")
        == (
            "R31 exact matrix-report consumer over the frozen R28 instrumented R17-derived local matrix; "
            "R30 owner-verified import and RECORD closure; fixed installed RECORD snapshot; "
            "synthetic provider and in-memory ZMQ only; no account acceptance"
        ),
        "r33_matrix_frame_contract_invalid",
    )
    results = report.get("results")
    _need(type(results) is list and len(results) == 16, "r33_matrix_frame_coverage_invalid")
    for case_id, result in zip(expected_ids, results):
        match = re.fullmatch(r"(D|GZ)-E([01])-R([01])-M([01])", case_id)
        expected = {
            "case_id": case_id,
            "selection": {
                "transport": "direct" if match.group(1) == "D" else "gateway_zmq",
                "execution": match.group(2) == "1",
                "risk": match.group(3) == "1",
                "monitor": match.group(4) == "1",
            },
        }
        _need(
            type(result) is dict
            and set(result) == {"case_id", "selection"}
            and type(result.get("case_id")) is str
            and type(result.get("selection")) is dict
            and _exact_public_tree(result, expected),
            "r33_matrix_frame_case_invalid",
        )
    return report


def _raw_writer(control, label, bounded):
    def persist():
        stdout, stderr = bounded.snapshot()
        _need(
            type(stdout) is bytes
            and type(stderr) is bytes
            and len(stdout) <= MAX_RAW_STDOUT
            and len(stderr) <= MAX_RAW_STDERR
        )
        control.write_bytes("r33-r5-" + label + "-stdout.bin", stdout)
        control.write_bytes("r33-r5-" + label + "-stderr.bin", stderr)

    return persist


def _child_environment(job_module):
    builder = getattr(job_module, "_minimal_environment", None)
    _need(callable(builder), "job_environment_builder_missing")
    source = builder()
    _need(
        type(source) is dict and set(source).issubset(_CHILD_ENV_KEYS),
        "job_environment_keys_invalid",
    )
    _need({"SYSTEMROOT", "WINDIR"}.issubset(source), "job_environment_required_key_missing")
    _need(
        ntpath.normcase(ntpath.normpath(source["SYSTEMROOT"]))
        == ntpath.normcase(ntpath.normpath(source["WINDIR"])),
        "job_environment_systemroot_mismatch",
    )
    environment = {}
    for key, value in source.items():
        _need(
            type(key) is str
            and key in _CHILD_ENV_KEYS
            and type(value) is str
            and value
            and "\x00" not in value
            and "\r" not in value
            and "\n" not in value,
            "job_environment_value_invalid",
        )
        if key == "SYSTEMDRIVE":
            _need(_DRIVE.fullmatch(value) is not None, "job_environment_drive_invalid")
        else:
            _need(ntpath.isabs(value), "job_environment_path_invalid")
    if "SYSTEMDRIVE" in source:
        _need(
            ntpath.normcase(ntpath.splitdrive(source["SYSTEMROOT"])[0])
            == ntpath.normcase(source["SYSTEMDRIVE"]),
            "job_environment_drive_mismatch",
        )
    environment.update(source)
    environment["PATH"] = _CHILD_PATH
    return environment


def _run_child_after_claim(
    control,
    private,
    cli,
    child_source,
    candidate_module,
    start_child,
    cleanup_adapter,
    job_module,
    *,
    deadline,
    lease_sink=None,
):
    """Launch one already-claimed child; raw bytes are saved before any parse."""
    child_path = CONTROL / "r33-root-r5-matrix-child.py"
    control.write_bytes(child_path.name, child_source)
    lease = cli._locked_readonly_file(child_path, private, private._api())
    if type(lease_sink) is dict:
        lease_sink["lease"] = lease
    handle, identity = lease.__enter__()
    api = private._api()
    api.verify_acl(handle, api.current_sid())
    _need(
        cli._locked_file_identity(api, handle, private) == identity
        and cli._read_bounded_handle(api, handle, MAX_CHILD_BYTES) == child_source,
        "child_source_readback_mismatch",
    )
    control.verify()
    command = [str(PYTHON_EXE), "-I", "-S", "-B", str(child_path)]
    env = _child_environment(job_module)
    kwargs = {
        "cwd": str(ROOT),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "close_fds": True,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    started = start_child(command, kwargs, control, deadline)
    if type(started) is not dict or started.get("kind") != "started":
        return {
            "status": "BLOCKED",
            "reason": "child_start_uncertain",
            "attempted": True,
            "lease": lease,
            "started": started,
            "raw_saved": bool(type(started) is dict and started.get("raw_capture_saved") is True),
            "clean": False,
        }
    job, bounded = started.get("job"), started.get("bounded")
    _need(job is not None and bounded is not None, "child_start_result_invalid")
    timed_out = communication_error = False
    try:
        bounded.communicate(timeout=max(0.0, deadline - time.monotonic()))
        timed_out = time.monotonic() >= deadline
    except subprocess.TimeoutExpired:
        timed_out = True
    except BaseException:
        communication_error = True
    stdout, stderr = bounded.snapshot()
    stdout_stats, stderr_stats = bounded.stats()
    overflow = bool(stdout_stats.get("overflow") or stderr_stats.get("overflow"))
    communication_error = communication_error or bool(
        stdout_stats.get("reader_error") or stderr_stats.get("reader_error")
    )
    persist_initial = (
        _raw_writer(control, "partial-initial", bounded)
        if timed_out or communication_error
        else None
    )
    persist_final = _raw_writer(
        control, "partial-final" if timed_out or communication_error else "complete", bounded
    )
    cleanup = cleanup_adapter(
        job,
        bounded,
        cleanup_seconds=CLEANUP_SECONDS,
        terminate=timed_out or communication_error,
        lease=lease,
        persist_initial=persist_initial,
        persist_final=persist_final,
    )
    stdout, stderr = bounded.snapshot()
    stdout_stats, stderr_stats = bounded.stats()
    overflow = overflow or bool(stdout_stats.get("overflow") or stderr_stats.get("overflow"))
    communication_error = communication_error or bool(
        stdout_stats.get("reader_error") or stderr_stats.get("reader_error")
    )
    raw_saved = bool(
        type(cleanup) is dict
        and cleanup.get("persist_done") is True
        and cleanup.get("persist_failed") is False
    )
    complete = bool(
        type(cleanup) is dict
        and cleanup.get("capture_complete") is True
        and not timed_out
        and not communication_error
        and not overflow
    )
    clean = bool(
        type(cleanup) is dict
        and cleanup.get("clean") is True
        and cleanup.get("child_script_lease_closed") is True
        and not communication_error
        and not overflow
    )
    base = {
        "attempted": True,
        "lease": lease,
        "started": started,
        "cleanup": cleanup,
        "raw_saved": raw_saved,
        "clean": clean,
        "raw_complete": complete,
        "timeout": timed_out,
        "communication_error": communication_error,
        "output_overflow": overflow,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
    }
    if not clean or not raw_saved or not complete:
        return {**base, "status": "BLOCKED", "reason": "child_cleanup_or_capture_unverified"}
    try:
        exit_code = cleanup.get("returncode")
        _need(type(exit_code) is int and exit_code in (0, 2), "child_exit_code_invalid")
        report = _parse_final(stdout, candidate_module)
        _need(
            _strict_zero(report.get("strict_cases_passed"))
            and report.get("case_pass") is False
            and report.get("registry_admission") is False
            and report.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16",
            "child_acceptance_projection_invalid",
        )
        status = (
            "LOCAL_DIAGNOSTIC_ONLY"
            if report.get("status") == "LOCAL_DIAGNOSTIC_ONLY"
            else "BLOCKED"
        )
        if status == "LOCAL_DIAGNOSTIC_ONLY":
            _need(
                exit_code == 0
                and type(report.get("case_count")) is int
                and report["case_count"] == 16
                and report.get("transport_cleanup_complete") is True,
                "child_matrix_completion_invalid",
            )
        else:
            _need(exit_code == 2 and report.get("status") == "BLOCKED")
        projection = {
            "schema": "iteration41.optional16.r33.root-matrix-projection.v3",
            "status": status,
            "reason": report.get("reason"),
            "completed_case_count": report.get("case_count", 0),
            "case_ids": [row["case_id"] for row in report.get("results", [])]
            if status == "LOCAL_DIAGNOSTIC_ONLY"
            else [],
            "cleanup": "CLEAN",
            "raw_capture_saved": True,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "strict_cases_passed": 0,
            "case_pass": False,
            "registry_admission": False,
            "acceptance": "NOT_ACCEPTED_OPTIONAL16",
            "provider_session_created": False,
            "network_access_allowed": False,
        }
        return {**base, "status": status, "reason": report.get("reason"), "projection": projection}
    except BaseException:
        return {**base, "status": "BLOCKED", "reason": "child_final_frame_invalid"}


def _load_exact(raw, path, name, pin):
    _need(type(raw) is bytes and _sha(raw) == pin, "root_module_pin_mismatch")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _m01_helper_compat_map(held):
    """Add the frozen R28 helper's two exact key spellings to held bytes."""
    helper_held = dict(held)
    for path in (M01_HELPER, M01_PACKET / "source-bundle.zip"):
        raw = _held(held, path)
        canonical = str(path)
        for key, value in held.items():
            _need(type(key) is str and type(value) is bytes, "m01_held_map_invalid")
            if _windows_path_key(key) == _windows_path_key(path):
                _need(value == raw, "m01_held_alias_conflict")
        existing = helper_held.get(canonical)
        _need(existing is None or existing == raw, "m01_held_alias_conflict")
        helper_held[canonical] = raw
    return helper_held


def _actual_start_factory(held, root_driver_module, private, cli, control):
    job_module = _load_exact(_held(held, JOB), JOB, "_iteration41_optional16_r31_job", JOB_SHA256)
    # CUV2 publishes normalized Windows path keys.  The already-frozen R28
    # helper consumes two exact, case-preserving string keys, so bridge only
    # those entries from the held map.  Keep the bytes sourced from `_held`;
    # never fall back to a disk read or accept a conflicting alias.
    helper_raw = root_driver_module._read_m01_helper_from_frozen_bundle(
        _m01_helper_compat_map(held)
    )
    helper = root_driver_module._contain_pinned_spawn_helper(
        _load_exact(
            helper_raw, M01_HELPER, "_iteration41_optional16_r31_m01_spawn", M01_HELPER_SHA256
        )
    )

    def cleanup_adapter(
        job, bounded, *, cleanup_seconds, terminate, lease, persist_initial=None, persist_final=None
    ):
        return root_driver_module._bounded_job_cleanup_r8(
            job,
            bounded,
            cleanup_seconds=cleanup_seconds,
            terminate=terminate,
            lease=lease,
            persist_initial=persist_initial,
            persist_final=persist_final,
        )

    cleanup_module = types.SimpleNamespace(_bounded_job_cleanup=cleanup_adapter)

    def start_child(command, kwargs, capture, deadline):
        return root_driver_module._run_bounded_start_r8(
            helper, job_module, command, kwargs, capture, cleanup_module, deadline=deadline
        )

    return start_child, cleanup_adapter, job_module, helper, cleanup_module


_LIFECYCLE_DIAGNOSTIC_SCHEMA = "iteration41.optional16.r33.child-lifecycle-diagnostic.r3.v1"
_LIFECYCLE_BOOL_FIELDS = (
    "timeout",
    "communication_error",
    "output_overflow",
    "raw_complete",
    "raw_saved",
    "clean",
)
_LIFECYCLE_HELPER_FIELDS = {
    "helper_capture_complete": "capture_complete",
    "helper_persist_done": "persist_done",
    "helper_persist_failed": "persist_failed",
    "helper_clean": "clean",
    "helper_child_script_lease_closed": "child_script_lease_closed",
}


def _public_lifecycle_diagnostic(state, *, source_postverified):
    """Project fixed lifecycle booleans after clean cleanup and source postverify only."""
    if (
        source_postverified is not True
        or type(state) is not dict
        or type(state.get("clean")) is not bool
        or state["clean"] is not True
    ):
        return None
    if any(type(state.get(name)) is not bool for name in _LIFECYCLE_BOOL_FIELDS):
        return None
    cleanup = state.get("cleanup")
    cleanup = cleanup if type(cleanup) is dict else {}
    result = {"schema": _LIFECYCLE_DIAGNOSTIC_SCHEMA}
    result.update({name: state[name] for name in _LIFECYCLE_BOOL_FIELDS})
    for public_name, helper_name in _LIFECYCLE_HELPER_FIELDS.items():
        value = cleanup.get(helper_name)
        result[public_name] = value if type(value) is bool else None
    return result


def _valid_public_lifecycle_diagnostic(value):
    if type(value) is not dict:
        return False
    required = {"schema", *_LIFECYCLE_BOOL_FIELDS, *_LIFECYCLE_HELPER_FIELDS}
    return (
        set(value) == required
        and value.get("schema") == _LIFECYCLE_DIAGNOSTIC_SCHEMA
        and all(type(value.get(name)) is bool for name in _LIFECYCLE_BOOL_FIELDS)
        and all(
            value.get(name) is None or type(value.get(name)) is bool
            for name in _LIFECYCLE_HELPER_FIELDS
        )
    )


def _valid_progress_diagnostic(value):
    if type(value) is not dict:
        return False
    required = {
        "schema",
        "availability",
        "reason_code",
        "capture_state",
        "phase_status",
        "phase_event_count",
        "last_phase",
        "active_phase",
        "matrix_status",
        "matrix_frame_count",
        "completed_case_count",
        "last_case_id",
        "active_stage",
        "last_elapsed_ms",
        "strict_cases_passed",
        "case_pass",
        "acceptance",
        "authority",
    }
    phase_names = {
        "candidate_module_load",
        "entry_preflight",
        "source_map",
        "root_template",
        "owner_source",
        "r9_source",
        "topology_selection",
        "site_presence",
        "distribution_inventory",
        "exact_closure",
        "diagnostic_policy",
        "network_guard",
        "installed_record_gate",
        "sdk_import",
        "sdk_guard",
        "payload_closure",
        "source_map_after_import",
        "gate_proof",
        "source_map_before_matrix",
        "matrix_source",
        "wire_source",
        "matrix_import_scope_enter",
        "pre_matrix_guard",
        "matrix_dispatch",
        "matrix_cleanup",
        "sdk_cleanup_guard",
        "manifest_close",
        "result_ready",
    }
    matrix_statuses = {
        "NOT_STARTED",
        "IN_PROGRESS",
        "FAILED_DIAGNOSTIC",
        "COMPLETE_DIAGNOSTIC",
        "INCOMPLETE",
        "UNAVAILABLE",
    }
    return (
        set(value) == required
        and value.get("schema") == "iteration41.optional16.r33.progress-diagnostic.r5.v1"
        and value.get("availability") in {"AVAILABLE", "UNAVAILABLE"}
        and (
            value.get("reason_code") is None
            or value.get("reason_code") in _PROGRESS_UNAVAILABLE_REASONS
        )
        and value.get("capture_state") in {"COMPLETE", "PREFIX", "UNAVAILABLE"}
        and value.get("phase_status")
        in {
            "NOT_STARTED",
            "IN_PROGRESS",
            "FAILED_DIAGNOSTIC",
            "COMPLETE_DIAGNOSTIC",
            "PREFIX",
            "UNAVAILABLE",
        }
        and (
            value.get("phase_event_count") is None
            or (
                type(value.get("phase_event_count")) is int
                and 0 <= value["phase_event_count"] <= 56
            )
        )
        and (value.get("last_phase") is None or value.get("last_phase") in phase_names)
        and (value.get("active_phase") is None or value.get("active_phase") in phase_names)
        and value.get("matrix_status") in matrix_statuses
        and (
            value.get("matrix_frame_count") is None
            or (
                type(value.get("matrix_frame_count")) is int
                and 0 <= value["matrix_frame_count"] <= 640
            )
        )
        and (
            value.get("completed_case_count") is None
            or (
                type(value.get("completed_case_count")) is int
                and 0 <= value["completed_case_count"] <= 16
            )
        )
        and (
            value.get("last_case_id") is None
            or value.get("last_case_id") == "MATRIX"
            or value.get("last_case_id")
            in {
                "D-E0-R0-M0",
                "D-E0-R0-M1",
                "D-E0-R1-M0",
                "D-E0-R1-M1",
                "D-E1-R0-M0",
                "D-E1-R0-M1",
                "D-E1-R1-M0",
                "D-E1-R1-M1",
                "D-E2-R0-M0",
                "D-E2-R0-M1",
                "D-E2-R1-M0",
                "D-E2-R1-M1",
                "D-E3-R0-M0",
                "D-E3-R0-M1",
                "D-E3-R1-M0",
                "D-E3-R1-M1",
            }
        )
        and (
            value.get("active_stage") is None
            or value.get("active_stage")
            in {
                "matrix",
                "case",
                "zmq_context_create",
                "gateway_server_start",
                "zmq_context_term",
                "execution_facade_close",
                "execution_store_close",
                "risk_gate_close",
                "matrix_temp_cleanup",
            }
        )
        and (
            value.get("last_elapsed_ms") is None
            or (
                type(value.get("last_elapsed_ms")) is int and 0 <= value["last_elapsed_ms"] <= 60000
            )
        )
        and type(value.get("strict_cases_passed")) is int
        and value.get("strict_cases_passed") == 0
        and value.get("case_pass") is False
        and value.get("acceptance") == "NOT_ESTABLISHED"
        and value.get("authority") == "DIAGNOSTIC_ONLY"
    )


def _safe_projection(state):
    diagnostic = state.get("_postverified_lifecycle") if type(state) is dict else None
    progress = state.get("_postverified_progress") if type(state) is dict else None
    postverified_clean = (
        type(state) is dict
        and state.get("clean") is True
        and _valid_public_lifecycle_diagnostic(diagnostic)
    )
    if not postverified_clean:
        return {
            "schema": "iteration41.optional16.r33.root-matrix-projection.v3",
            "status": "BLOCKED",
            "reason": state.get("reason", "root_operation_failed")
            if type(state) is dict
            else "root_operation_failed",
            "cleanup": "UNCERTAIN",
            "raw_capture_saved": None,
            "strict_cases_passed": 0,
            "case_pass": False,
            "registry_admission": False,
            "acceptance": "NOT_ACCEPTED_OPTIONAL16",
            "provider_session_created": False,
            "network_access_allowed": False,
        }
    if type(state.get("projection")) is dict:
        projection = dict(state["projection"])
    else:
        projection = {
            "schema": "iteration41.optional16.r33.root-matrix-projection.v3",
            "status": "BLOCKED",
            "reason": state.get("reason", "root_operation_failed"),
            "cleanup": "CLEAN",
            "strict_cases_passed": 0,
            "case_pass": False,
            "registry_admission": False,
            "acceptance": "NOT_ACCEPTED_OPTIONAL16",
            "provider_session_created": False,
            "network_access_allowed": False,
        }
    projection["raw_capture_saved"] = diagnostic["raw_saved"]
    projection["child_lifecycle"] = diagnostic
    if _valid_progress_diagnostic(progress):
        projection["progress_diagnostic"] = dict(progress)
    return projection


def run_once():
    """Run one root-held diagnostic. Caller must fill activation fields in memory."""
    _need(_activation_ready(), "root_activation_unset")
    pins, software, _duplicate_path_aliases = _expected_pins()
    _verify_disk_pins(pins)
    _verify_disk_pins(software)
    cu = _load_exact(_read_pin(CU, CU_SHA256), CU, "_iteration41_optional16_r31_custody", CU_SHA256)
    source_scope = cu.held_public_sources(pins, software)
    private = cli = held = control = scratch = lease = root_driver_module = None
    progress_lease = None
    job_module = helper = cleanup_module = None
    attempted = False
    retain = False
    outcome = None
    lease_sink = {}
    try:
        private, cli, held = source_scope.__enter__()
        _validate_r1_upstream_lineage(held)
        _validate_r2_predecessor_lineage(held)
        _validate_candidate_review(held)
        _validate_r33_candidate_review(held)
        _validate_r28_lineage(held)
        _validate_driver_review(held)
        candidate_parser = _candidate_parser(held)
        control = private.create_private_directory(CONTROL)
        scratch = private.create_private_directory(SCRATCH)
        control.verify()
        scratch.verify()
        progress_lease = _open_progress_lease(control, private)
        scratch.write_bytes(
            "r33-source-bundle.sha256", R33_PACKET_PINS["source-bundle.zip"].encode("ascii")
        )
        child_source = _build_child_source(
            _held(held, R33_CANDIDATE),
            _held(held, SNAPSHOT),
            progress_lease["path"],
        )
        # Claim is CREATE_NEW, sticky, and written before Job module load/Popen/Job creation.
        control.write_bytes("r33-r5-once.claim", b"iteration41-optional16-r33-root-r5-once-v1\n")
        deadline = _r15_invocation_deadline(time.monotonic())
        root_driver_module = _load_exact(
            _read_pin(R28_ROOT_DRIVER, R28_ROOT_DRIVER_SHA256),
            R28_ROOT_DRIVER,
            "_iteration41_optional16_r31_r28_primitives",
            R28_ROOT_DRIVER_SHA256,
        )
        start_child, cleanup_adapter, job_module, helper, cleanup_module = _actual_start_factory(
            held, root_driver_module, private, cli, control
        )
        attempted = True
        outcome = _run_child_after_claim(
            control,
            private,
            cli,
            child_source,
            candidate_parser,
            start_child,
            cleanup_adapter,
            job_module,
            deadline=deadline,
            lease_sink=lease_sink,
        )
        lease = lease_sink.get("lease")
        clean = type(outcome) is dict and outcome.get("clean") is True
        if not clean:
            retain = True
            _KEEPALIVES.extend(
                [
                    source_scope,
                    private,
                    cli,
                    held,
                    control,
                    scratch,
                    lease,
                    root_driver_module,
                    job_module,
                    helper,
                    cleanup_module,
                    outcome,
                    progress_lease,
                ]
            )
            root_driver_module._RETAIN_CUSTODY = True
            root_driver_module._retain_r8(
                source_scope,
                private,
                cli,
                held,
                control,
                scratch,
                lease,
                root_driver_module,
                job_module,
                helper,
                cleanup_module,
                outcome,
                progress_lease,
                outcome.get("lease") if type(outcome) is dict else None,
                outcome.get("started") if type(outcome) is dict else None,
            )
        else:
            control.verify()
            scratch.verify()
            root_driver_module._RETAIN_CUSTODY = False
            source_scope.__exit__(None, None, None)
            source_scope = None
            try:
                progress = _read_progress_after_postverify(
                    progress_lease,
                    private,
                    cli,
                    candidate_parser,
                    timed_out=type(outcome) is dict and outcome.get("timeout") is True,
                )
                outcome = {**outcome, "_postverified_progress": progress}
                _close_progress_lease(progress_lease)
                progress_lease = None
            except BaseException:
                retain = True
                _KEEPALIVES.extend(
                    [
                        private,
                        cli,
                        held,
                        control,
                        scratch,
                        lease,
                        root_driver_module,
                        job_module,
                        helper,
                        cleanup_module,
                        outcome,
                        progress_lease,
                    ]
                )
                root_driver_module._RETAIN_CUSTODY = True
                root_driver_module._retain_r8(
                    private,
                    cli,
                    held,
                    control,
                    scratch,
                    lease,
                    root_driver_module,
                    job_module,
                    helper,
                    cleanup_module,
                    outcome,
                    progress_lease,
                )
                outcome = {
                    **outcome,
                    "status": "BLOCKED",
                    "reason": "progress_sidecar_readback_unverified",
                    "_progress_readback_failed": True,
                }
            lifecycle = _public_lifecycle_diagnostic(outcome, source_postverified=True)
            if lifecycle is not None:
                outcome = {**outcome, "_postverified_lifecycle": lifecycle}
            if (
                outcome.get("_progress_readback_failed") is True
                and type(outcome.get("projection")) is dict
            ):
                projection = dict(outcome["projection"])
                projection["status"] = "BLOCKED"
                projection["reason"] = "progress_sidecar_readback_unverified"
                projection.pop("progress_diagnostic", None)
                outcome = {**outcome, "projection": projection}
        result = _safe_projection(outcome)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result.get("status") == "LOCAL_DIAGNOSTIC_ONLY" else 2
    except BaseException as error:
        if type(lease_sink) is dict and lease_sink.get("lease") is not None:
            lease = lease_sink["lease"]
        if attempted or lease is not None:
            retain = True
            _KEEPALIVES.extend(
                [
                    source_scope,
                    private,
                    cli,
                    held,
                    control,
                    scratch,
                    lease,
                    root_driver_module,
                    job_module,
                    helper,
                    cleanup_module,
                    outcome,
                    progress_lease,
                ]
            )
            if root_driver_module is not None:
                root_driver_module._RETAIN_CUSTODY = True
                root_driver_module._retain_r8(
                    source_scope,
                    private,
                    cli,
                    held,
                    control,
                    scratch,
                    lease,
                    job_module,
                    helper,
                    cleanup_module,
                    outcome,
                    progress_lease,
                    outcome.get("lease") if type(outcome) is dict else None,
                    outcome.get("started") if type(outcome) is dict else None,
                )
        else:
            if progress_lease is not None:
                try:
                    _close_progress_lease(progress_lease)
                    progress_lease = None
                except BaseException:
                    retain = True
                    _KEEPALIVES.append(progress_lease)
                    if root_driver_module is not None:
                        root_driver_module._RETAIN_CUSTODY = True
                        root_driver_module._retain_r8(progress_lease)
            if source_scope is not None:
                try:
                    source_scope.__exit__(None, None, None)
                except BaseException:
                    retain = True
                    _KEEPALIVES.append(source_scope)
        print(
            json.dumps(
                {
                    "schema": "iteration41.optional16.r33.root-matrix-projection.v3",
                    "status": "BLOCKED",
                    "reason": (
                        "parent_deadline_budget_insufficient"
                        if type(error) is _ParentDeadlineBlocked
                        else "root_operation_failed"
                    ),
                    "cleanup": "UNCERTAIN" if retain else "NOT_STARTED",
                    "strict_cases_passed": 0,
                    "case_pass": False,
                    "registry_admission": False,
                    "acceptance": "NOT_ACCEPTED_OPTIONAL16",
                    "provider_session_created": False,
                    "network_access_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--public-check"]:
        print(json.dumps(public_check(), sort_keys=True, separators=(",", ":")))
        return 0
    if args:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "arguments_rejected",
                    "strict_cases_passed": 0,
                    "acceptance": "NOT_ACCEPTED_OPTIONAL16",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    if not _activation_ready():
        print(
            json.dumps(
                {
                    "status": "PREPARED_UNSET",
                    "reason": "root_activation_unset",
                    "strict_cases_passed": 0,
                    "case_pass": False,
                    "registry_admission": False,
                    "acceptance": "NOT_ACCEPTED_OPTIONAL16",
                    "provider_session_created": False,
                    "network_access_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    try:
        _r15_invocation_deadline(time.monotonic())
    except _ParentDeadlineBlocked:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "parent_deadline_budget_insufficient",
                    "strict_cases_passed": 0,
                    "case_pass": False,
                    "registry_admission": False,
                    "acceptance": "NOT_ACCEPTED_OPTIONAL16",
                    "provider_session_created": False,
                    "network_access_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
