# Security Policy

## Supported Versions

| Branch | 定位 | 安全修复策略 |
|---|---|---|
| `master` | 原始 Backtrader 基线 | 仅修复在原始版复现的安全问题（`hotfix/master-*`） |
| `development` | 改进与优化版本 | 仅修复在优化版复现的安全问题 |
| `dev` | 日常开发入口 | 常规安全问题先在此落地 |

## Reporting a Vulnerability

**请勿在公开 issue、讨论或 PR 中披露漏洞细节。**

请通过 GitHub 私密报告路径提交：

- GitHub Security Advisory：<https://github.com/cloudQuant/backtrader/security/advisories/new>

### 报告内容

请尽量包含：

1. 受影响的分支/版本；
2. 漏洞类型与影响范围（数据泄露、代码执行、拒绝服务等）；
3. 最小复现步骤；
4. 建议的修复方向（可选）。

### 响应承诺

- 维护者将在 **5 个工作日内**确认收到报告；
- 将在修复与公开披露前与你保持沟通；
- 若你希望在公开披露前保密，请明确说明，维护者将配合协调披露时间；
- 公开披露将遵循 [GitHub 的协调披露](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities) 流程。

## 范围

本策略适用于 `cloudQuant/backtrader` 仓库内的代码与配置。依赖库的漏洞请直接上报对应上游项目，或通过上述私密路径告知维护者。

## 不在公开渠道处理

- 不公开提交 API key、令牌、凭据或漏洞细节；
- 已公开的凭据请立即轮换，并通过私密路径告知维护者。
