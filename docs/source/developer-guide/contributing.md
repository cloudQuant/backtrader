---
title: Contributing to Backtrader
description: Guidelines for contributing to Backtrader
---

# Contributing to Backtrader

Thank you for your interest in contributing to Backtrader! This document provides guidelines and workflows for contributing to the project.

## Table of Contents

- [Getting Started](#getting-started)
- [Pull Request Workflow](#pull-request-workflow)
- [Code Review Standards](#code-review-standards)
- [Issue Reporting Guidelines](#issue-reporting-guidelines)
- [Community Guidelines](#community-guidelines)
- [License and Contributor Agreement](#license-and-contributor-agreement)
- [Developer Certificate of Origin](#developer-certificate-of-origin-dco)

## Getting Started

### Prerequisites

- Python 3.8 or higher
- Git
- Basic knowledge of Python programming
- Familiarity with quantitative trading concepts (helpful but not required)

### First Time Setup

```bash
# 1. Fork the repository on GitHub
#    Click "Fork" button at https://github.com/cloudQuant/backtrader

# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/backtrader.git
cd backtrader

# 3. Add upstream remote
git remote add upstream https://github.com/cloudQuant/backtrader.git

# 4. Install dependencies
pip install -r requirements.txt

# 5. Install in development mode
pip install -e .

# 6. Compile Cython extensions (recommended for performance)
cd backtrader && python -W ignore compile_cython_numba_files.py && cd ..
```

### Branch Naming Conventions

Use descriptive branch names that indicate the type of change:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat/` | New feature | `feat/websocket-reconnect` |
| `fix/` | Bug fix | `fix/indicator-calculation` |
| `refactor/` | Code refactoring | `refactor/broker-optimization` |
| `docs/` | Documentation | `docs/api-reference` |
| `test/` | Test improvements | `test/coverage-increase` |
| `perf/` | Performance | `perf/line-buffer-cache` |

## Pull Request Workflow

### Step 1: Create a Feature Branch

```bash
# Sync with upstream
git fetch upstream
git checkout dev
git merge upstream/dev

# Create your feature branch
git checkout -b feat/your-feature-name
```

### Step 2: Make Your Changes

- Write clean, readable code
- Follow the [Code Style](style.md) guidelines
- Add tests for new functionality
- Update documentation as needed

### Step 3: Commit Your Changes

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <description>

[optional body]
```

**Valid types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactoring
- `docs`: Documentation changes
- `test`: Test additions or modifications
- `chore`: Maintenance tasks
- `perf`: Performance improvements

**Examples:**

```bash
git commit -m "feat: add WebSocket health check to CCXTFeed"
git commit -m "fix: handle order-not-found in CCXTBroker.cancel()"
git commit -m "perf: cache broker reference in total_value.next()"
git commit -m "docs: update CCXT live trading guide"
```

### Step 4: Run Tests

```bash
# Run pre-commit tests (P0 + P1)
pytest tests/ -v -m "priority_p0 or priority_p1"

# Run full test suite
pytest tests/ -v -n 4

# Check code formatting
make format-check

# Run linting
make lint
```

### Step 5: Push and Create Pull Request

```bash
# Push to your fork
git push origin feat/your-feature-name

# Create pull request on GitHub
# Target: dev branch
```

### Pull Request Description Template

```markdown
## Summary
Brief description of what this PR does and why.

## Changes
- List of major changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Performance improvement
- [ ] Documentation update
- [ ] Refactoring
- [ ] Breaking change

## Testing
- Describe testing approach
- Include test commands
```bash
pytest tests/path/to/test.py -v
```

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] CHANGELOG.md updated (for user-facing changes)
- [ ] No merge conflicts with target branch

## Related Issues
Fixes #123
Related to #456
```

## Code Review Standards

### Review Process

1. **Automated Checks**: All PRs must pass CI/CD checks
2. **Peer Review**: At least one maintainer approval required
3. **Test Coverage**: New code requires corresponding tests
4. **Documentation**: API changes require documentation updates

### Review Criteria

Maintainers review pull requests for:

| Aspect | Criteria |
|--------|----------|
| **Functionality** | Works as intended, no regressions |
| **Code Quality** | Readable, maintainable, follows conventions |
| **Testing** | Adequate coverage, edge cases handled |
| **Documentation** | Clear docstrings, user-facing changes documented |
| **Performance** | No significant degradation, optimizations documented |

### Addressing Review Feedback

- Respond to all review comments
- Make requested changes or provide justification
- Mark conversations as resolved when addressed
- Request re-review after significant changes

### Approval Requirements

- Small changes: Single maintainer approval
- Medium changes: Two maintainer approvals
- Large/Complex changes: Core team consensus

## Issue Reporting Guidelines

### Bug Reports

Include the following information:

```markdown
## Environment
- Python version: 3.11.0
- Operating system: Ubuntu 22.04
- Backtrader version: 1.0.0 (dev branch)
- Installation method: pip install -e .

## Description
Clear description of the bug.

## Steps to Reproduce
1. Create a Cerebro instance
2. Add data feed with...
3. Run strategy
4. Observe error

## Expected Behavior
What should happen.

## Actual Behavior
What actually happens (include error messages).

## Code Sample
```python
import backtrader as bt

# Minimal reproducible example
```

## Additional Context
Logs, screenshots, or other relevant information.
```

### Feature Requests

Provide the following information:

```markdown
## Problem Statement
What problem does this solve? What is the use case?

## Proposed Solution
Detailed description of the desired feature.

## Alternatives Considered
What other approaches did you consider?

## Additional Context
Examples, references, or implementation ideas.
```

## Community Guidelines

### Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Assume good intentions

### Communication Channels

- **Issues**: Bug reports and feature requests
- **Discussions**: Questions and ideas
- **Pull Requests**: Code contributions

### Getting Help

- Search existing issues and discussions first
- Provide minimal reproducible examples
- Share relevant environment details
- Be patient with volunteer maintainers

## License and Contributor Agreement

### License

Backtrader is licensed under the GNU General Public License v3.0 (GPLv3).

By contributing to Backtrader, you agree that your contributions will be licensed under the GPLv3.

### Copyright

Copyright is retained by the original contributor. The project includes attribution in:

- LICENSE file
- CONTRIBUTORS file
- Release notes

## Developer Certificate of Origin (DCO)

### What is DCO?

The DCO is a simple statement that you certify you have the right to submit your contribution.

### DCO Sign-off

To certify your contribution, add a `Signed-off-by` line to your commit messages:

```bash
git commit -m "feat: add new indicator

Signed-off-by: Your Name <your.email@example.com>"
```

### Automatic Sign-off

Configure Git to automatically add sign-off:

```bash
git config --global commit.signoff true
```

Then use `-s` flag:

```bash
git commit -s -m "feat: add new indicator"
```

### DCO Certification

By signing off, you certify:

> Developer Certificate of Origin
> Version 1.1
>
> Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
> 1 Letterman Drive
> Suite D4700
> San Francisco, CA, 94129
>
> Everyone is permitted to copy and distribute verbatim copies of this
> license document, but changing it is not allowed.
>
>
> Developer's Certificate of Origin 1.1
>
> By making a contribution to this project, I certify that:
>
> (a) The contribution was created in whole or in part by me and I
>     have the right to submit it under the open source license
>     indicated in the file; or
>
> (b) The contribution is based upon previous work that, to the best
>     of my knowledge, is covered under an appropriate open source
>     license and I have the right under that license to submit that
>     work with modifications, whether created in whole or in part
>     by me, under the same open source license (unless I am
>     permitted to submit under a different license), as indicated
>     in the file; or
>
> (c) The contribution was provided directly to me by some other
>     person who certified (a), (b) or (c) and I have not modified
>     it.
>
> (d) I understand and agree that this project and the contribution
>     are public and that a record of the contribution (including all
>     personal information I submit with it, including my sign-off) is
>     maintained indefinitely and may be redistributed consistent with
>     this project or the open source license(s) involved.

## Recognition

Contributors are recognized in:

- `CONTRIBUTORS` file
- Release notes
- Project documentation (for significant contributions)

Thank you for contributing to Backtrader!

## See Also

- [Development Setup](setup.md)
- [Code Style](style.md)
- [Testing Guide](testing.md)
- [Project Context](../project-context.md)
