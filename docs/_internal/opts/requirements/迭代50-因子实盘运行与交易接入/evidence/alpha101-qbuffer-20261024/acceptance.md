# AC50-16b 全101循环缓冲验收

结论：**PASS（SOURCE / COMPOSITION）**。与已接受的16a合并，AC50-16父项通过同一层级。此结果不代表性能、安装、真实行情或账户验收。

2026-10-24（Asia/Shanghai）22:15:01开始，约23:26:29自然完成。pytest终端为1 passed、1条既有`asyncio_default_fixture_loop_scope`配置警告，耗时4288.22秒；JUnit为1 testcase、0 errors/failures/skips、4288.222秒。完成后工具session已不可查询，没有单独保存的进程退出码，因此不另称已核验exit 0。Root未重复成功测试，独立只读审查`i51_strategy`核对源码、原始结果及判据后GO。

工作目录为`D:/source_code/backtrader`，解释器为本机Python 3.11.5；设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONUTF8=1`，执行：

```powershell
python -u -m pytest -s -p no:asyncio --junitxml=.codex-tmp/ac50_16b_full_qbuffer_native_build_r2_20261024.xml tests/unit/test_factor_operator_logical_buffers.py::test_alpha101_full_and_qbuffer_native_build_values_and_reasons_match
```

启动提交为`c610cc84e580ae74dad84cbcc39469eb1f667092`；归档前HEAD为`d95ce054ee752103863689e296ef8b23e9b278e4`。期间其他独立小轮有提交；下列五个实际输入的启动/结束指纹一致，Root归档时再次核对，没有将整个工作区描述为不变。

| 输入 | SHA-256 |
|---|---|
| `backtrader/research/operators.py` | `fbf6d142f40564ade20a0a4f160fffde6876c343d9943f4e74671dbac70dfb42` |
| `backtrader/research/specs.py` | `0b14ce92d0d747c38951a993d4d9dd526c37cef4476cc78a9279b849402c5208` |
| `tests/unit/test_factor_operator_logical_buffers.py` | `2d2cbb626e611aab6e0105b12b2fadf440f71c1f1ea0bb7d45518d7d042dce67` |
| `backtrader/linebuffer.py` | `e898cb6b81d580fd03c0a6f9cad5272a3651a6787b32c009da017f5a014f2bc3` |
| `backtrader/research/factor_strategy.py` | `1b5237d7ce1dc698fba509187d17b88bd75b806473775e4c867c449f9806fd86` |

实际普通FactorStrategy/Cerebro在六资产、3072个计划格上配对完整buffer与QBuffer；native/build各六批，共12条完整结果。逐节点value/reason流与最终矩阵严格一致，每个公式均有post-history有限且非零见证。输入包含asset-1中点真实缺行、asset-3的NaN high及asset-4末端NaN close。容量在实际策略回调中按精确line identity采样，检查target/input/value/reason、直接输入身份和value/reason配对，不依赖EOF后的空单槽推断。

| 公式批次（两种mode各一遍） | 最大configured/实际retained | 完整翻转次数 |
|---|---:|---:|
| 1–20 | 251 / 251 | 12 |
| 21–40 | 251 / 251 | 12 |
| 41–60 | 252 / 252 | 12 |
| 61–80 | 239 / 239 | 12 |
| 81–100 | 121 / 121 | 25 |
| 101 | 2 / 2 | 1536 |

原始输出按字节复制，未整理或重写：

- [pytest-output.txt](pytest-output.txt)：23765字节，SHA-256 `b86951f358fc2f80bab36f011e77f972b2112159077a1fda564d9e603ad32c05`。
- [pytest.xml](pytest.xml)：380字节，SHA-256 `28435170e862bb2537b3ab874ef9529026b897342214587a53ee4ae27b339a0f`。

此前R1的EOF后单槽容量误判及失败输出保留，修复和独立焦点验收见提交`c610cc84`及提交记录。本次长测没有降低值/reason、缺格、有效值或翻转门槛。耗时仅为该测试诊断，不能替代AC50-27的正式延迟与资源验收。
