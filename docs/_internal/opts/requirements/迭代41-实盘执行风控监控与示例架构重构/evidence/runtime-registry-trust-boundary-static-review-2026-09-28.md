# Runtime registry trust boundary static review (2026-09-28)

**Disposition:** evidence-only; no source patch recommended.

## Scope

Static review of the current `backtrader_runtime` registry, inventory, CLI, and runner flow. The SHA-256 values below identify the working-tree bytes reviewed on 2026-09-28; they are not commit or release identifiers. No tests or runtime commands were run. No SDK, native provider, credentials, network, account, order, or live route was used.

## Findings

- The installed `bt-runtime` entry point calls `backtrader_runtime.cli:main` without arguments (`setup.py:115`), and `python -m backtrader_runtime` likewise calls `main()` without a registry (`backtrader_runtime/__main__.py:6`). With no injected registry, `main` selects `default_runtime_registry()` (`backtrader_runtime/cli.py:1323-1342`), which returns the code-owned `iteration41_runtime_registry()` inventory (`backtrader_runtime/registry.py:1049-1062`; `backtrader_runtime/inventory.py:329-358`). Thus the shipped CLI is inventory-bound at its entry point.
- `main(registry=...)` is a separate Python API, explicitly documented for reviewed application code and unit tests (`backtrader_runtime/cli.py:1331-1336`). A caller-provided registry is therefore a same-process trust delegation by the embedding application.
- `RuntimeRegistry` defaults `trusted=True` (`backtrader_runtime/registry.py:575-585`), stores the value as an ordinary mutable `self.trusted` attribute (`:735`), and execution/preflight checks test that boolean (`:766-771`, `:788-812`, `:1028-1048`). This is a cooperative assertion. It does not authenticate registry construction, caller identity, or registration provenance; code in the same process can also set the attribute.
- Runner source binding is exact for shipped inventory records (`backtrader_runtime/runner.py:749-805`). A custom registration with no such binding reaches the normal `importlib.import_module(module_name)` fallback (`:1134-1145`); the registry API does not sandbox arbitrary same-process runner code. The effective-config seal binds a resolved value to its registry object, but does not establish that a caller-supplied registry came from the shipped inventory.
- `dispatch_registered_runtime` rejects `mode=live` before runner dispatch when verified production admission is unavailable (`backtrader_runtime/runner.py:1175-1185`). This review found no change that authorizes live dispatch or writes.

## Assessment

Changing the constructor default or adding another caller-settable trust flag would make some callers state their trust choice explicitly, but would not close arbitrary same-process injection: the embedding application controls the registry, can opt in, and can invoke Python code directly. A strict shipped-inventory-only gate would also change the documented application-injection surface used by legitimate fake and replay integrations. No narrow source change was identified that both preserves that surface and makes caller-supplied registrations code-authenticated.

Treat custom registry injection as trusted application code, not as an isolation boundary. A future threat model that includes partially trusted in-process callers needs an external admission boundary or process isolation; a boolean on this object is insufficient. This review does not establish writer closure, live/provider/account acceptance, or safety of arbitrary injected runner code.

## Source fingerprints

| Workspace source path | SHA-256 |
| --- | --- |
| `backtrader_runtime/registry.py` | `F359E0D0576662BC8D5F966EF2345FE723C8802CD504AD383323E59959FE5A01` |
| `backtrader_runtime/inventory.py` | `0EBC77EFD22E21B299E794E09C8CB879899B5DC4EFD3302E86D2D9C626B0F6CB` |
| `backtrader_runtime/cli.py` | `BCA2632E261FE2B663008E8B0758C2C932DF917F9376E9B90230848B41EF5EF4` |
| `backtrader_runtime/runner.py` | `F80C4DE5C8E981F73B2C05930BB5F772F631099CE3A8291AF94E7BAC0DCB6AFD` |
| `backtrader_runtime/__main__.py` | `36053545F4682A69C27B05CB17C38872E7C4A2F5933F7D38ABBBDCDE14B57DD0` |
| `setup.py` | `4B9CA54FC287EE9D618B581AD2879BAB68226C77ED940D8B0FBAFE33A67569E7` |
