---
name: backtrader-repo-toolkit
description: Repository maintenance toolkit for the Backtrader codebase. This skill should be used when analyzing code size and docstring coverage, cleaning Markdown formatting, parsing pytest duration logs, comparing cProfile logs, scanning logging baselines, running selected tests with logs or timeouts, or cleaning A-share daily CSV columns. Provides standalone scripts copied from the repository's scripts/ directory, plus a catalog of which repository scripts are reusable versus iteration-bound.
agent_created: true
---

# Backtrader Repo Toolkit

## Overview

Standalone helpers for recurring Backtrader repository maintenance tasks. All bundled scripts are pure Python (standard library only, except where noted), take CLI arguments, and can be run from any working directory. They were extracted from `scripts/` because they are general-purpose rather than tied to a specific iteration, account, or data file.

## Quick Start

Run a bundled script directly with Python:

```bash
python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/analyze_code_lines.py [repo-root]
python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/clean_markdown.py --help
```

Every script exposes `--help` (except `analyze_test_durations.py`, which takes a log path as positional argument). When in doubt, run with `--help` first to confirm arguments and output paths.

## Task Catalog

### Code and documentation analysis

| Task | Script | Typical invocation |
| --- | --- | --- |
| Count total/code/blank lines by file type and directory | `analyze_code_lines.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/analyze_code_lines.py .` |
| Find missing module/class/function docstrings and Chinese comments | `analyze_docstrings.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/analyze_docstrings.py --summary` |
| Scan `except`/logger/print sites into JSON catalogs (iteration 29 baseline format) | `scan_logging_baseline.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/scan_logging_baseline.py --out <dir>` |

`analyze_docstrings.py` accepts a path to a single file or a directory tree; options include `--verbose` and `--summary`. `scan_logging_baseline.py` emits `excepts.json`, `logger-calls.json`, and `prints.json`; bokeh/plot visualization paths are exempt per the repository's baseline rule.

### Markdown and text cleanup

| Task | Script | Typical invocation |
| --- | --- | --- |
| Fix Markdown lint issues (heading spacing, trailing whitespace, list/code-block spacing) | `clean_markdown.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/clean_markdown.py <path> [--check]` |

`clean_markdown.py` has a companion shell wrapper `scripts/clean_markdown.sh` in the repository that discovers and processes all Markdown files; the Python script is the portable core. Always preview changes with its check/dry-run option before applying to documentation directories.

### Performance and test analysis

| Task | Script | Typical invocation |
| --- | --- | --- |
| Summarize slowest tests from a `pytest --durations=0` log | `analyze_test_durations.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/analyze_test_durations.py <logfile>` |
| Compare two cProfile/pstats text logs and report regressions | `compare_performance_logs.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/compare_performance_logs.py <baseline> <current>` |
| Run a test script while teeing output to a git-branch-named log | `run_test_with_log.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/run_test_with_log.py <test_script> [--both]` |
| Verify native/build factor pair semantics | `verify_factor_research_pair_semantics.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/verify_factor_research_pair_semantics.py --help` |
| Render a GitHub ruleset JSON payload | `render_github_ruleset_payload.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/render_github_ruleset_payload.py --help` |

`analyze_test_durations.py` reads the log path from `sys.argv[1]` and has no `--help`. It aggregates setup+call+teardown seconds per test. `run_test_with_log.py --both` runs the test against both the current branch and master/origin — only use when both branches are available locally.

### Data cleanup

| Task | Script | Typical invocation |
| --- | --- | --- |
| Clean/normalize A-share daily CSV columns (with hash and manifest output) | `clean_a_stock_daily_columns.py` | `python D:/source_code/backtrader/skills/backtrader-repo-toolkit/scripts/clean_a_stock_daily_columns.py --help` |

This script uses only the standard library (`csv`, `hashlib`, `json`, `pathlib`, `shutil`). It is data-file specific but not tied to a single iteration; pass input/output paths via CLI.

## Workflow Guidance

1. **Identify the task** from the catalog above. If the task is not listed, check `references/script_inventory.md` for a classification of the full repository `scripts/` directory before writing a new helper — an existing script may already cover it.
2. **Verify the script version** matches the checkout. The bundled scripts are a snapshot; if behavior differs from the current repository script, prefer the repository copy for that checkout and report the drift.
3. **Run with `--help` first**, then execute on a small scope. For cleanup tools (`clean_markdown.py`, `clean_a_stock_daily_columns.py`), use dry-run/check mode before writing.
4. **Never run scripts that are not bundled here** from the repository's `scripts/` directory without reading them first. Many are iteration-bound, one-shot migration tools or historical certification wrappers that can rewrite source, consume frozen evidence, or require real credentials. The inventory reference marks these.

## Safety Boundaries

- No bundled script connects to a broker, exchange, or database, and none reads credentials.
- Do not use this toolkit to authorize live trading, account access, or deployment. It is repository maintenance only.
- Scripts that modify files (`clean_markdown.py`, `clean_a_stock_daily_columns.py`) must be run on a clean working tree or with a backup so changes are reviewable.
- Historical certification scripts in the repository (`run_simnow_*`, `run_iter27_*`, `iteration50/51_installed_fixture.py`, etc.) are intentionally excluded: they are frozen evidence, not current entry points.

## Resources

### scripts/
Ten standalone Python helpers, described in the Task Catalog. Standard library only.

### references/
- `script_inventory.md` — classification of every script in `D:/source_code/backtrader/scripts/` into reusable, iteration-bound/one-shot, CI infrastructure, and needs-review groups, with deletion recommendations and evidence.
