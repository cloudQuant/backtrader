# Iteration10：certlib 可安装发行物

范围：新增 certlib/pyproject.toml，发行 bt-api-binance-certlib 0.1.0，Python>=3.11、PyYAML>=6.0,<7；仅现有七个公开Python模块，不改原有案例/runner行为。

仓库/分支：Backtrader/dev，验收父提交be07a50ed3b4ddb5b419855827e7a965d5230b84；实际提交SHA见本文件Git历史。本轮只提交配置和本记录，其他测试草稿和CTP等WIP保留。

Root从固定源构建真实sdist与wheel，在两个独立新venv离线安装，七模块均为site-packages来源且与源hash一致；分别正常调用已安装runner.main_case dry入口，两次退出0，无网络/客户端启动。原始结果D:/temp/it10-mig04-certlib-r1-20261016-k4focatf/result.json，检查脚本SHA256 0f743027349ffcb61c7eb6a770b78225b009c0489d17bdb99702b35bf0f1affe，独立最终静态复审GO。初始未运行检查脚本的缺colorama与生成setup.cfg白名单错误在执行前修正；没有失败后重复构建。

本轮仅接受certlib包安装/普通dry入口子项。原default_env_path依赖目录层级，本次使用全新且确认不存在的容器.env，未读取用户.env；不声称修复live凭据发现，也不直接恢复MIG04全组合PASS。旧10-wheel矩阵证据保留，新组合兼容性另验。对应原始输出归档于SDK迭代10 evidence/certlib-package-20261016。
