.PHONY: help test test-original lint format type-check security install dev-install clean docs docs-en docs-zh docs-clean docs-offline docs-offline-zh docs-view docs-view-zh

DOCS_BUILD_DIR := docs/_build/html
DOCS_MPLCONFIGDIR ?= $(CURDIR)/docs/.mplconfig

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package
	pip install -e .

dev-install:  ## Install development dependencies
	pip install -r requirements.txt
	pip install -e .

test:  ## Run all tests
	python -m pytest tests/original_tests/ -v --tb=short

test-original:  ## Run only original tests (excluding crypto tests)
	python -m pytest tests/original_tests/ -v --tb=short --html=tests/report.html

test-coverage:  ## Run tests with coverage
	python -m pytest tests/original_tests/ --cov=backtrader --cov-report=html --cov-report=term

lint:  ## Run pylint
	pylint backtrader --rcfile=.pylintrc

format:  ## Format code with black
	black backtrader tests/original_tests --line-length=100

format-check:  ## Check if code is formatted
	black --check backtrader tests/original_tests --line-length=100

type-check:  ## Run mypy type checking
	mypy backtrader --config-file=pyproject.toml

security:  ## Run security checks
	bandit -r backtrader -f json -o security-report.json
	safety check

quality-check:  ## Run all quality checks
	make format-check
	make lint
	make type-check
	make security

pre-commit:  ## Run pre-commit checks
	make format
	make quality-check
	make test-original

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

benchmark:  ## Run performance benchmarks
	python -m pytest tests/original_tests/ --benchmark-only

docs:  ## Generate all documentation (en + zh)
	$(MAKE) docs-offline
	$(MAKE) docs-offline-zh

docs-en:  ## Generate English documentation
	$(MAKE) docs-offline

docs-zh:  ## Generate Chinese documentation
	$(MAKE) docs-offline-zh

docs-offline:  ## Build English docs locally without network-only extensions
	mkdir -p $(DOCS_BUILD_DIR)/en $(DOCS_MPLCONFIGDIR)
	DOCS_OFFLINE=1 BUILD_LANGUAGE=en MPLCONFIGDIR=$(DOCS_MPLCONFIGDIR) \
		python -m sphinx -b html docs/source $(DOCS_BUILD_DIR)/en

docs-offline-zh:  ## Build Chinese docs locally without network-only extensions
	mkdir -p $(DOCS_BUILD_DIR)/zh $(DOCS_MPLCONFIGDIR)
	DOCS_OFFLINE=1 BUILD_LANGUAGE=zh MPLCONFIGDIR=$(DOCS_MPLCONFIGDIR) \
		python -m sphinx -b html -D language=zh_CN -D root_doc=index_zh -D master_doc=index_zh \
		docs/source $(DOCS_BUILD_DIR)/zh

docs-clean:  ## Clean generated documentation
	rm -rf docs/_build

docs-view:  ## Open English documentation in browser
	open $(DOCS_BUILD_DIR)/en/index.html

docs-view-zh:  ## Open Chinese documentation in browser
	open $(DOCS_BUILD_DIR)/zh/index_zh.html

git-setup:  ## Setup git hooks for development
	@echo "Setting up git hooks..."
	@echo "#!/bin/sh\nmake pre-commit" > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Git hooks setup complete"

analyze-metaclass:  ## Analyze metaclass usage in the codebase
	@echo "Analyzing metaclass usage..."
	grep -r "metaclass" backtrader --include="*.py" | wc -l
	@echo "Files using metaclass:"
	grep -r "metaclass" backtrader --include="*.py" -l

analyze-dynamic:  ## Analyze dynamic class creation
	@echo "Analyzing dynamic class creation..."
	grep -r "type(" backtrader --include="*.py" | wc -l
	@echo "Files using type() for dynamic creation:"
	grep -r "type(" backtrader --include="*.py" -l

analyze-metaprogramming:  ## Full metaprogramming analysis
	@echo "=== Metaprogramming Analysis ==="
	@echo "1. Metaclass usage:"
	@make analyze-metaclass
	@echo "\n2. Dynamic class creation:"
	@make analyze-dynamic
	@echo "\n3. setattr/getattr usage:"
	@grep -r "setattr\|getattr" backtrader --include="*.py" | wc -l
	@echo "\n4. Files with heavy metaprogramming:"
	@grep -r "metaclass\|type(\|setattr\|getattr" backtrader --include="*.py" -l | sort | uniq -c | sort -nr 
