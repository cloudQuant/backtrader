# Monitor read-only events R3 Root local gate

Acceptance classification: **LOCAL_COMPONENT_ONLY**. The accepted monitor child commit is `dac72780c33ac181fa90bb4acf7cd4845916543c` on dev; the accepted `bt_api_py` parent commit is `0666742c650f94d2dcd1d2eb0f7c757eeea438ee` on dev.

Root's synthetic child check completed startup, served the synthetic auth page, and exited normally. The local gate did not import the SDK parent (`bt_api_py`) and did not call an account or provider. Formal case pass count remains 0. This does not establish live/provider acceptance.

The script checked four source origins and verified the pinned source bytes before and after pytest:

| Origin check | Expected source path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `bt_api_base` | `D:\bt_api_py\bt_api\bt_api_base\src` | directory origin check | — |
| `bt_api_monitor` | `D:\bt_api_py\bt_api\bt_api_monitor\src\bt_api_monitor\__init__.py` | 5,970 | `f0b816c83f92d0e01ccc92f8f9e20ba67acde7ccb439289c4148ea581574617a` |
| `bt_api_monitor.durable` | `D:\bt_api_py\bt_api\bt_api_monitor\src\bt_api_monitor\durable.py` | 25,889 | `fec232682272bd1295a12821222a7d687ee59ca9a2c216b080f7eb67b3706f0e` |
| `bt_api_monitor.readonly_events` | `D:\bt_api_py\bt_api\bt_api_monitor\src\bt_api_monitor\readonly_events.py` | 27,217 | `91e2dd7c9f19b2b09b4b22247506e800135e513448f9aca11a73fb0ed5363631` |

The test source pin was also verified before and after: `D:\bt_api_py\bt_api\bt_api_monitor\tests\test_readonly_events.py`, 26,508 bytes, SHA-256 `e3ed4e4bbf7e28b5d1fc21c4f0267c7b06785b273e2c5366b4269119b3e4ce8a`.

Root recorded 21 passed in 1.65s, exit 0, no warnings. The script-written `observation.json` independently records a 1.735s observation interval. `command.md` distinguishes the recorded tool result from that captured JSON. The source script is copied byte-for-byte as `root-local-gate.py`; `observation.json` is unchanged.