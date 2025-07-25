# Git Sync Setup Guide / Git 同步设置指南

This guide explains how to set up automatic synchronization between Gitee and GitHub repositories.

本指南说明如何设置 Gitee 和 GitHub 仓库之间的自动同步。

## Method 1: GitHub Actions (Automatic) / 方法1：GitHub Actions（自动）

### Prerequisites / 前提条件

1. Create a Personal Access Token on GitHub / 在 GitHub 上创建个人访问令牌
   - Go to https://github.com/settings/tokens
   - Click "Generate new token (classic)"
   - Select scopes: `repo` (full control of private repositories)
   - Copy the generated token

2. Add the token to your Gitee repository secrets / 将令牌添加到 Gitee 仓库密钥
   - Go to your Gitee repository settings
   - Navigate to CI/CD → Secret Variables
   - Add a new secret named `SYNC_GITHUB_TOKEN` with your GitHub token

### How it works / 工作原理

The `.github/workflows/sync.yml` workflow will automatically:
- Trigger on pushes to master, main, or dev branches
- Push all changes to https://github.com/cloudQuant/backtrader.git

## Method 2: Manual Sync Scripts / 方法2：手动同步脚本

### For Windows Users / Windows 用户

Run the batch script after pushing to Gitee:

```batch
sync_to_github.bat
```

### For Linux/Mac Users / Linux/Mac 用户

Make the script executable and run:

```bash
chmod +x sync_to_github.sh
./sync_to_github.sh
```

## Method 3: Git Alias (Recommended) / 方法3：Git 别名（推荐）

Add this alias to your git configuration:

```bash
git config --global alias.push-all '!git push origin && git push github'
```

Then use:

```bash
git push-all
```

## Method 4: Multiple Push URLs / 方法4：多个推送 URL

Configure git to push to both repositories simultaneously:

```bash
# Add GitHub as a push URL to origin
git remote set-url --add --push origin https://github.com/cloudQuant/backtrader.git
git remote set-url --add --push origin https://gitee.com/yunjinqi/backtrader.git
```

Now `git push` will push to both repositories.

## Troubleshooting / 故障排除

### Authentication Issues / 认证问题

If you encounter authentication errors:

1. For HTTPS, use a personal access token instead of password
2. For SSH, ensure your SSH keys are properly configured

```bash
# Test GitHub connection
ssh -T git@github.com

# Test Gitee connection  
ssh -T git@gitee.com
```

### Force Push Protection / 强制推送保护

If the GitHub repository has force push protection:

1. Remove `--force` from the sync scripts
2. Ensure branches are not diverged between repositories

## Security Note / 安全说明

- Never commit tokens or passwords to the repository
- Use GitHub Secrets for CI/CD workflows
- Regularly rotate your access tokens

---

For more help, please open an issue at https://gitee.com/yunjinqi/backtrader/issues