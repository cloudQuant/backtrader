# Documentation Reorganization Plan

- *Status**: Planning Phase
- *Created**: 2026-03-01
- *Target Completion**: TBD

## Executive Summary

This document outlines a comprehensive plan to reorganize the Backtrader documentation structure to follow Sphinx and technical documentation best practices. The current structure has several issues including inconsistent naming, duplicate directories, mixed languages at root level, and internal documentation mixed with user-facing content.

### Current Problems Identified

1. **Inconsistent Naming Convention**
   - `api_reference` vs `api-reference` (underscore vs hyphen)
   - `developer-guide` vs `developer-guide-zh` (language suffix vs separate directory)

1. **Duplicate/Overlapping Directories**
   - `api_reference/` (minimal content) vs `api-reference/` (extensive content)
   - `architecture/` at root vs `advanced/architecture/` (duplicate concepts)
   - `reference/` overlaps with `api-reference/`

1. **Language Management Issues**
   - Separate `-zh` directories at root level (`user-guide-zh`, `developer-guide-zh`, `getting-started-zh`)
   - Mixed language files within same directories (`*_zh.md` alongside `*.md`)
   - Not following Sphinx i18n best practices (single source with `.po` translations)

1. **Internal vs External Documentation**
   - `opts/` contains internal optimization notes mixed with user docs
   - `_project/` is internal but at same level as user-facing content
   - Build artifacts (`_build/`) not properly excluded

1. **Inconsistent File Formats**
   - Mix of `.md`, `.rst`, and `.py` (Jupyter) files
   - Some directories have both formats

## Target Structure

The reorganized structure follows Sphinx conventions and separates concerns:

```bash
docs/

|-- source/                    # Sphinx source (single source of truth)

|   |-- _static/              # Static assets (CSS, JS, images)

|   |-- _templates/           # Custom Jinja templates

|   |-- conf.py               # Sphinx configuration

|   |-- index.rst             # English main index

|   |-- index_zh.rst          # Chinese main index

|   |

|   |-- getting-started/      # User guide: getting started

|   |   |-- installation.rst

|   |   |-- quickstart.rst

|   |   |-- README.md

|   |

|   |-- user-guide/           # User guide: core usage

|   |   |-- concepts/

|   |   |   |-- basic-concepts.rst

|   |   |   |-- line-system.rst

|   |   |   |-- phase-system.rst

|   |   |-- data-feeds/

|   |   |   |-- overview.rst

|   |   |   |-- csv.rst

|   |   |   |-- pandas.rst

|   |   |   |-- live/

|   |   |       |-- ccxt.rst

|   |   |       |-- ctp.rst

|   |   |-- indicators/

|   |   |-- strategies/

|   |   |-- analyzers/

|   |   |-- brokers/

|   |   |-- visualization/

|   |   |-- optimization/

|   |   |-- faq.rst

|   |

|   |-- api/                  # API reference (auto-generated)

|   |   |-- cerebro.rst

|   |   |-- strategy.rst

|   |   |-- indicators.rst

|   |   |-- analyzers.rst

|   |   |-- feeds/

|   |   |-- brokers/

|   |   |-- indicators/

|   |   |-- observers/

|   |   |-- sizers/

|   |   |-- stores/

|   |

|   |-- advanced/             # Advanced topics

|   |   |-- ts-mode.rst

|   |   |-- cs-mode.rst

|   |   |-- multi-strategy.rst

|   |   |-- data-acquisition.rst

|   |   |-- performance-optimization.rst

|   |   |-- profiling.rst

|   |   |-- architecture/

|   |   |   |-- overview.rst

|   |   |   |-- line-system.rst

|   |   |   |-- phase-system.rst

|   |   |-- live-trading/

|   |

|   |-- developer-guide/      # Developer documentation

|   |   |-- contributing.rst

|   |   |-- setup.rst

|   |   |-- testing.rst

|   |   |-- style.rst

|   |   |-- release.rst

|   |   |-- code-quality.rst

|   |

|   |-- tutorials/            # Tutorial examples

|   |   |-- complete-strategy.rst

|   |   |-- notebook-guide.rst

|   |   |-- examples/

|   |   |-- notebooks/

|   |

|   |-- migration/            # Migration guides

|   |   |-- from-original.rst

|   |   |-- upgrade.rst

|   |

|   |-- reference/            # Quick reference materials

|   |   |-- quick-reference.rst

|   |   |-- terminology.rst

|   |   |-- optimization-docs/

|   |

|   |-- support/              # Support resources

|   |   |-- search-guide.rst

|   |   |-- troubleshooting.rst

|   |

|   |-- locales/              # Translations (Sphinx i18n)

|   |   |-- zh_CN/

|   |   |   |-- LC_MESSAGES/

|   |   |   |   |-- index.po

|   |   |   |   |-- getting-started/

|   |   |   |   |-- user-guide/

|   |   |   |   |-- api/

|   |   |   |   |-- advanced/

|   |   |   |   |-- developer-guide/

|   |   |   |   |-- tutorials/

|   |   |   |   |-- migration/

|   |   |   |   |-- reference/

|   |   |   |   |-- support/

|

|-- _build/                   # Build output (gitignored)

|-- _archive/                 # Archived old docs (kept for reference)

|-- _internal/                # Internal project documentation (not published)

|   |-- opts/                 # Internal optimization notes

|   |-- _project/             # Project planning docs

|   |-- planning/             # Development planning

|

|-- Makefile                  # Build automation

|-- make.bat                  # Windows build automation

|-- requirements.txt          # Documentation dependencies

|-- README.md                 # Documentation readme

|-- _REORGANIZATION_PLAN.md   # This document

```bash

## Directory Migration Mapping

### User-Facing Documentation Moves

| Current Path | Target Path | Notes |

|-------------|-------------|-------|

| `getting-started/*` | `source/getting-started/` | Keep as-is, just move |

| `getting-started-zh/*` | `source/locales/zh_CN/LC_MESSAGES/getting-started/*.po` | Convert to .po files |

| `user-guide/*` | `source/user-guide/` | Reorganize into subdirectories |

| `user-guide-zh/*` | `source/locales/zh_CN/LC_MESSAGES/user-guide/*.po` | Convert to .po files |

| `api_reference/*` | `source/api/` | Merge with api-reference |

| `api-reference/*` | `source/api/` | Reorganize into subdirectories |

| `developer-guide/*` | `source/developer-guide/` | Remove Chinese suffix files |

| `developer-guide-zh/*` | `source/locales/zh_CN/LC_MESSAGES/developer-guide/*.po` | Convert to .po files |

| `advanced/*` | `source/advanced/` | Keep structure |

| `architecture/*` | `source/advanced/architecture/` | Merge into advanced |

| `tutorials/*` | `source/tutorials/` | Keep as-is |

| `migration/*` | `source/migration/` | Keep as-is |

| `reference/*` | `source/reference/` | Keep as-is |

| `support/*` | `source/support/` | Keep as-is |

### Internal Documentation Moves

| Current Path | Target Path | Notes |

|-------------|-------------|-------|

| `opts/` | `_internal/opts/` | Internal optimization notes |

| `_project/` | `_internal/_project/` | Project planning documents |

### Archive

| Current Path | Target Path | Notes |

|-------------|-------------|-------|

| `_archive/` | `_archive/` | Keep as-is for reference |

| Build artifacts | Delete | Rebuild from new structure |

## File-by-File Move Operations

### Phase 1: Prepare Directories

```bash

# Create new directory structure

mkdir -p docs/source/getting-started
mkdir -p docs/source/user-guide/{concepts,data-feeds/live,indicators,strategies,analyzers,brokers,visualization,optimization}
mkdir -p docs/source/api/{feeds,brokers,indicators,observers,sizers,stores}
mkdir -p docs/source/advanced/{architecture,live-trading}
mkdir -p docs/source/developer-guide
mkdir -p docs/source/tutorials/{examples,notebooks}
mkdir -p docs/source/migration
mkdir -p docs/source/reference/optimization-docs
mkdir -p docs/source/support

# Create internal directory

mkdir -p docs/_internal

# Create locale directories

mkdir -p docs/source/locales/zh_CN/LC_MESSAGES/{getting-started,user-guide,api,advanced,developer-guide,tutorials,migration,reference,support}

```bash

### Phase 2: Move User Documentation

```bash

# Getting started

mv docs/getting-started/* docs/source/getting-started/

# User guide - reorganize into subdirectories

mv docs/user-guide/concept*.md docs/source/user-guide/concepts/
mv docs/user-guide/concept*.rst docs/source/user-guide/concepts/
mv docs/user-guide/data*.md docs/source/user-guide/data-feeds/
mv docs/user-guide/data*.rst docs/source/user-guide/data-feeds/
mv docs/user-guide/ccxt*.md docs/source/user-guide/data-feeds/live/
mv docs/user-guide/ctp*.md docs/source/user-guide/data-feeds/live/
mv docs/user-guide/indicator*.md docs/source/user-guide/indicators/
mv docs/user-guide/indicator*.rst docs/source/user-guide/indicators/
mv docs/user-guide/strategies.* docs/source/user-guide/strategies/
mv docs/user-guide/analyzers.* docs/source/user-guide/analyzers/
mv docs/user-guide/brokers.* docs/source/user-guide/brokers/
mv docs/user-guide/performance.* docs/source/user-guide/visualization/
mv docs/user-guide/optimization.* docs/source/user-guide/optimization/
mv docs/user-guide/faq.* docs/source/user-guide/
mv docs/user-guide/live_trading.* docs/source/user-guide/data-feeds/live/
mv docs/user-guide/visualization.* docs/source/user-guide/visualization/
mv docs/user-guide/installation.* docs/source/getting-started/
mv docs/user-guide/quickstart.* docs/source/getting-started/

# API reference - merge directories

mv docs/api_reference/* docs/source/api/
mv docs/api-reference/* docs/source/api/

# Developer guide

mv docs/developer-guide/*.md docs/source/developer-guide/
mv docs/developer-guide/*.rst docs/source/developer-guide/

# Advanced topics

mv docs/advanced/* docs/source/advanced/

# Architecture - merge into advanced

mv docs/architecture/* docs/source/advanced/architecture/

# Tutorials

mv docs/tutorials/* docs/source/tutorials/

# Migration

mv docs/migration/* docs/source/migration/

# Reference

mv docs/reference/* docs/source/reference/

# Support

mv docs/support/* docs/source/support/

```bash

### Phase 3: Move Internal Documentation

```bash

# Move internal docs

mv docs/opts docs/_internal/
mv docs/_project docs/_internal/

```bash

### Phase 4: Handle Translations

```bash

# Create translation extraction script

# This will extract strings from all .rst/.md files to create .po files

# See "Sphinx conf.py Changes" section for setup

```bash

### Phase 5: Clean Up

```bash

# Remove empty old directories

rmdir docs/getting-started docs/getting-started-zh
rmdir docs/user-guide docs/user-guide-zh
rmdir docs/api_reference docs/api-reference
rmdir docs/developer-guide docs/developer-guide-zh
rmdir docs/architecture

```bash

## Link Update Requirements

### Internal Cross-References

After restructuring, internal links need to be updated:

1. **Relative Links**: Update paths to reflect new directory structure
2. **Sphinx Cross-References**: Use proper `:ref:` and `:doc:` directives
3. **API Links**: Update to use new `:mod:` and `:class:` references

### Link Translation Patterns

| Old Link Pattern | New Link Pattern |

|------------------|------------------|

| `../user-guide/concepts.md` | `:doc:`user-guide/concepts`` |

| `../api-reference/strategy.md` | `:doc:`api/strategy`` |

| `developer-guide/contributing.rst` | `:doc:`developer-guide/contributing`` |

| `../advanced/ts-mode.md` | `:doc:`advanced/ts-mode`` |

### External Link Updates

1. **README.md**: Update documentation links
2. **setup.py/pyproject.toml**: Update project URLs if pointing to docs
3. **GitHub/GitLab**: Update wiki links and issue templates
4. **ReadTheDocs**: Update documentation home page and subprojects

## .gitignore Recommendations

Create `docs/.gitignore`:

```gitignore

# Sphinx build outputs

_build/
_static/
_templates/

# Generated files

- .pyc

__pycache__/

# Locale intermediate files (keep .po, ignore .mo)

locales/*/LC_MESSAGES/*.mo

# Sphinx auto-generated

.doctrees/
.pickle

# OS files

.DS_Store
Thumbs.db

# Editor files

.vscode/
.idea/

- .swp
- ~

# Notebooks output

.ipynb_checkpoints/

- */.ipynb_checkpoints/*

# Temporary files

_temp/

- .tmp

```bash
Update root `.gitignore`:

```gitignore

# Documentation build

docs/_build/
docs/_static/
docs/.doctrees/

# Notebooks

- */.ipynb_checkpoints/
- */.pytest_cache/

# Internal documentation (optional - exclude from published docs)

# docs/_internal/

```bash

## Sphinx conf.py Changes

### Required Updates

```python

# docs/source/conf.py

# Update project paths

sys.path.insert(0, os.path.abspath('../..'))

# Add i18n extension

extensions = [

# ... existing extensions ...
    'sphinx.ext.intersphinx',
    'sphinx_intl',  # Add for i18n support

]

# i18n configuration

locale_dirs = ['locales/']
gettext_compact = False  # Don't combine all .po files

gettext_uuid = True
gettext_location = True

# Language detection for ReadTheDocs

on_rtd = os.environ.get('READTHEDOCS', None) == 'True'
rtd_language = os.environ.get('READTHEDOCS_LANGUAGE', 'en')

if rtd_language in ('zh', 'zh_CN', 'zh-cn'):
    language = 'zh_CN'
    master_doc = 'index_zh'
    root_doc = 'index_zh'
    html_title = 'Backtrader 中文文档'
else:
    language = 'en'
    master_doc = 'index'
    root_doc = 'index'
    html_title = 'Backtrader Documentation'

# Exclude patterns

exclude_patterns = [
    '_build',
    'Thumbs.db',
    '.DS_Store',
    '_internal',
    '**/_internal',
]

# HTML theme options with language switcher

html_theme_options = {
    'navigation_with_keys': True,
    'source_repository': '<https://github.com/cloudQuant/backtrader/',>
    'source_branch': 'development',
    'source_directory': 'docs/source/',

# ... other options ...

}

```bash

### Makefile Updates

```makefile

# docs/Makefile

SPHINXOPTS  ?=
SPHINXBUILD  ?= sphinx-build
SOURCEDIR    = source
BUILDDIR     = _build
I18NSPHINXOPTS  = $(SPHINXOPTS) .

.PHONY: help clean html livehtml htmlhelp

help:
    @echo "Please use 'make <target>' where <target> is one of"
    @echo "  html        to make standalone HTML files"
    @echo "  livehtml    to serve HTML with live reload"
    @echo "  gettext     to extract translatable messages"
    @echo "  locale      to compile translations"

clean:
    rm -rf $(BUILDDIR)/*

gettext:
    $(SPHINXBUILD) -b gettext $(I18NSPHINXOPTS) $(SOURCEDIR) build/gettext
    @echo "Build finished. Translatable messages extracted."

locale:
    $(SPHINXINTL) update -p build/gettext -l zh_CN
    @echo "Translation files updated for zh_CN"

html:
    $(SPHINXBUILD) -b html $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/html
    @echo "Build finished. The HTML pages are in $(BUILDDIR)/html."

html-zh:
    $(SPHINXBUILD) -b html -D language=zh_CN $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/html/zh
    @echo "Build finished. The Chinese HTML pages are in $(BUILDDIR)/html/zh."

livehtml:
    sphinx-autobuild -b html $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/html

```bash

## ReadTheDocs Configuration

Create `.readthedocs.yaml`:

```yaml

# .readthedocs.yaml

version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.10"

sphinx:
  configuration: docs/source/conf.py
  fail_on_warning: false

python:
  install:

    - requirements: docs/requirements.txt
    - method: pip

      path: .

subprojects:

# English (default)

  - name: backtrader

    contents: docs/source

# Chinese

  - name: backtrader-zh

    contents: docs/source/locales/zh_CN

```bash

## Step-by-Step Execution Checklist

### Phase 1: Preparation (Before Any Moves)

- [ ] **Backup current documentation**
  - [ ] Create git branch: `git checkout -b docs/reorganization`
  - [ ] Create archive of current docs: `tar czf docs-backup-$(date +%Y%m%d).tar.gz docs/`

- [ ] **Audit existing documentation**
  - [ ] Create inventory of all files
  - [ ] Identify all cross-references
  - [ ] Map all language pairs (en/zh)

- [ ] **Set up new directory structure**
  - [ ] Create all target directories
  - [ ] Update .gitignore files

### Phase 2: File Migration

- [ ] **Move getting-started documentation**
  - [ ] Move `getting-started/` to `source/getting-started/`
  - [ ] Extract `getting-started-zh/` to .po files

- [ ] **Move user-guide documentation**
  - [ ] Reorganize into subdirectories
  - [ ] Move English content
  - [ ] Extract Chinese translations to .po files

- [ ] **Merge and move API documentation**
  - [ ] Merge `api_reference/` into `api/`
  - [ ] Move `api-reference/` to `api/`
  - [ ] Organize into subdirectories
  - [ ] Extract translations

- [ ] **Move developer documentation**
  - [ ] Move `developer-guide/` to `source/developer-guide/`
  - [ ] Extract `developer-guide-zh/` to .po files

- [ ] **Move advanced documentation**
  - [ ] Move `advanced/` to `source/advanced/`
  - [ ] Merge `architecture/` into `source/advanced/architecture/`

- [ ] **Move tutorials and reference**
  - [ ] Move `tutorials/` to `source/tutorials/`
  - [ ] Move `migration/` to `source/migration/`
  - [ ] Move `reference/` to `source/reference/`
  - [ ] Move `support/` to `source/support/`

- [ ] **Move internal documentation**
  - [ ] Move `opts/` to `_internal/opts/`
  - [ ] Move `_project/` to `_internal/_project/`

### Phase 3: Configuration Updates

- [ ] **Update Sphinx configuration**
  - [ ] Modify `source/conf.py`
  - [ ] Add i18n settings
  - [ ] Update exclude patterns

- [ ] **Update build automation**
  - [ ] Update Makefile
  - [ ] Update make.bat
  - [ ] Update build_docs.sh

- [ ] **Add ReadTheDocs config**
  - [ ] Create `.readthedocs.yaml`
  - [ ] Configure subprojects

### Phase 4: Link and Content Updates

- [ ] **Update internal cross-references**
  - [ ] Find and replace old paths
  - [ ] Convert to Sphinx directives
  - [ ] Verify all links resolve

- [ ] **Update external links**
  - [ ] Update README.md
  - [ ] Update setup.py/pyproject.toml
  - [ ] Check GitHub/GitLab references

- [ ] **Extract translations**
  - [ ] Run `sphinx-build -b gettext`
  - [ ] Create .po files for Chinese
  - [ ] Import existing Chinese content

### Phase 5: Testing and Validation

- [ ] **Build English documentation**
  - [ ] `make html`
  - [ ] Check for warnings
  - [ ] Verify all pages render

- [ ] **Build Chinese documentation**
  - [ ] `make html-zh`
  - [ ] Check for warnings
  - [ ] Verify translations display

- [ ] **Test locally**
  - [ ] Run `make livehtml`
  - [ ] Navigate all sections
  - [ ] Verify links work

- [ ] **Test on ReadTheDocs**
  - [ ] Deploy to staging
  - [ ] Verify language switcher
  - [ ] Check all subprojects

### Phase 6: Cleanup

- [ ] **Remove old directories**
  - [ ] Delete empty old directories
  - [ ] Clean up any residual files

- [ ] **Archive old structure**
  - [ ] Move old content to `_archive/`
  - [ ] Document migration history

- [ ] **Update documentation**
  - [ ] Update this plan with actual changes
  - [ ] Create migration guide for contributors
  - [ ] Update CLAUDE.md with new paths

### Phase 7: Final Steps

- [ ] **Commit changes**
  - [ ] Review all changes
  - [ ] Create comprehensive commit message
  - [ ] Submit for review

- [ ] **Merge and deploy**
  - [ ] Merge to main branch
  - [ ] Deploy to production
  - [ ] Announce changes to contributors

## Migration Scripts

### Automated Link Update Script

```python

# !/usr/bin/env python3

"""
Script to update internal documentation links after restructuring.
"""
import re
import os
from pathlib import Path

LINK_MAPPINGS = {
    r'\.\./user-guide/': ':doc:`user-guide/',
    r'\.\./api-reference/': ':doc:`api/',
    r'\.\./api_reference/': ':doc:`api/',
    r'\.\./developer-guide/': ':doc:`developer-guide/',
    r'\.\./advanced/': ':doc:`advanced/',
    r'\.\./getting-started/': ':doc:`getting-started/',
    r'\.\./tutorials/': ':doc:`tutorials/',
    r'\.\./migration/': ':doc:`migration/',
}

def update_links_in_file(file_path):
    """Update documentation links in a single file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    for old_pattern, new_pattern in LINK_MAPPINGS.items():
        content = re.sub(old_pattern, new_pattern, content)

    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {file_path}")

def process_directory(directory):
    """Process all documentation files in directory."""
    for file_path in Path(directory).rglob('*.rst'):
        update_links_in_file(file_path)
    for file_path in Path(directory).rglob('*.md'):
        update_links_in_file(file_path)

if __name__ == '__main__':
    process_directory('docs/source')

```bash

### Translation Extraction Script

```bash

# !/bin/bash

# extract-translations.sh

echo "Extracting translatable strings..."
sphinx-build -b gettext source/ build/gettext

echo "Creating/Updating Chinese translation files..."
sphinx-intl update -p build/gettext -l zh_CN

echo "Copying existing Chinese content to .po files..."

# This would require manual script to merge existing *_zh.md into .po format

echo "Done! Review .po files in source/locales/zh_CN/LC_MESSAGES/"

```bash

## Risk Mitigation

### Potential Issues and Solutions

| Risk | Impact | Mitigation |

|------|--------|------------|

| Broken links | High | Automated link checking, comprehensive testing |

| Lost translations | High | Keep backups, gradual migration, verify all .po files |

| Build failures | Medium | Test build after each phase, maintain rollback ability |

| Contributor confusion | Medium | Clear documentation, migration guide, transition period |

| ReadTheDocs issues | Medium | Test on staging, coordinate with RTD support |

### Rollback Plan

If issues arise during migration:

1. **Revert branch**: `git checkout main` and delete migration branch
2. **Restore backup**: Extract from `docs-backup-YYYYMMDD.tar.gz`
3. **Document issues**: Update this plan with lessons learned

## Success Criteria

The reorganization is successful when:

- [ ] All documentation builds without warnings
- [ ] Both English and Chinese versions are accessible
- [ ] All internal links work correctly
- [ ] Language switcher functions properly
- [ ] No duplicate content remains
- [ ] Internal docs are separated from user docs
- [ ] Build artifacts are properly gitignored
- [ ] All contributors can build documentation locally
- [ ] ReadTheDocs deployment works correctly

## Post-Migration Tasks

After successful migration:

1. **Update contributing guide**with new documentation structure

2.**Create README for `docs/`**explaining structure
3.**Set up pre-commit hooks**for link checking
4.**Automate translation workflow**

1. **Archive this plan** to `_archive/`

## References

- Sphinx i18n documentation: <https://www.sphinx-doc.org/en/master/usage/advanced/intl.html>
- Sphinx-intl documentation: <https://sphinx-intl.readthedocs.io/>
- ReadTheDocs best practices: <https://docs.readthedocs.io/>
- Diátaxis framework for documentation: <https://diataxis.fr/>

- --

- *Document Status**: Ready for Review
- *Next Steps**: Review and approve plan, begin Phase 1
