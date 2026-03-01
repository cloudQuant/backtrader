# Makefile for Sphinx documentation
#
# You can set these variables from the command line.
SPHINXOPTS    ?= -j auto
SPHINXBUILD   ?= sphinx-build
SPHINXINTL    ?= sphinx-intl
SOURCEDIR     = source
BUILDDIR      = _build
LOCALEDIR     = source/locales

# Put it first so that "make" without argument is like "make help".
help:
	@echo "╔══════════════════════════════════════════════════╗"
	@echo "║     Backtrader Documentation Build System       ║"
	@echo "╚══════════════════════════════════════════════════╝"
	@echo ""
	@echo "  html          Build English HTML documentation"
	@echo "  html-zh       Build Chinese HTML documentation"
	@echo "  html-all      Build both English and Chinese"
	@echo "  gettext       Extract translatable strings"
	@echo "  update-po     Update translation .po files"
	@echo "  clean         Remove build directory"
	@echo "  livehtml      Live-reload server (English)"
	@echo "  livehtml-zh   Live-reload server (Chinese)"
	@echo "  serve         Build all + start local HTTP server"
	@echo "  pdf           Build PDF via LaTeX"
	@echo "  apidoc        Generate API rst from source code"
	@echo "  linkcheck     Check for broken links"
	@echo ""

.PHONY: help Makefile html html-zh html-all gettext update-po clean livehtml livehtml-zh serve pdf apidoc linkcheck

# Build English HTML
html:
	@echo "▶ Building English documentation..."
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html/en" $(SPHINXOPTS)
	@echo "✔ English docs → $(BUILDDIR)/html/en/index.html"

# Build Chinese HTML
html-zh:
	@echo "▶ Building Chinese documentation..."
	BUILD_LANGUAGE=zh $(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html/zh" \
		-D language=zh_CN -D root_doc=index_zh -D master_doc=index_zh $(SPHINXOPTS)
	@echo "✔ Chinese docs → $(BUILDDIR)/html/zh/index_zh.html"

# Build both languages
html-all: html html-zh
	@echo ""
	@echo "✔ All documentation built successfully!"
	@echo "  English: $(BUILDDIR)/html/en/index.html"
	@echo "  Chinese: $(BUILDDIR)/html/zh/index_zh.html"

# Extract translatable strings
gettext:
	@echo "▶ Extracting translatable strings..."
	$(SPHINXBUILD) -b gettext "$(SOURCEDIR)" "$(BUILDDIR)/gettext" $(SPHINXOPTS)
	@echo "✔ Gettext files → $(BUILDDIR)/gettext"

# Update translation files
update-po: gettext
	@echo "▶ Updating translation files..."
	$(SPHINXINTL) update -p "$(BUILDDIR)/gettext" -l zh_CN -d "$(LOCALEDIR)"
	@echo "✔ PO files → $(LOCALEDIR)/zh_CN/LC_MESSAGES"

# Clean build directory
clean:
	rm -rf "$(BUILDDIR)"
	@echo "✔ Build directory cleaned."

# Live reload server for English
livehtml:
	@echo "▶ Starting live-reload server (English)..."
	sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html/en" $(SPHINXOPTS) --port 8000

# Live reload server for Chinese
livehtml-zh:
	@echo "▶ Starting live-reload server (Chinese)..."
	BUILD_LANGUAGE=zh sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html/zh" \
		-D language=zh_CN -D root_doc=index_zh -D master_doc=index_zh \
		$(SPHINXOPTS) --port 8001

# Build all + local HTTP server
serve: html-all
	@cat > "$(BUILDDIR)/html/index.html" <<- 'LANDING' \
	<!DOCTYPE html> \
	<html><head><meta charset="utf-8"><title>Backtrader Docs</title> \
	<style>body{font-family:system-ui,sans-serif;max-width:520px;margin:100px auto;text-align:center} \
	h1{color:#1565C0} .btn{display:inline-block;margin:12px;padding:14px 36px;background:#1565C0; \
	color:#fff;text-decoration:none;border-radius:8px;font-size:17px;transition:background .2s} \
	.btn:hover{background:#0D47A1} .btn.gitee{background:#C71D23} .btn.gitee:hover{background:#A01018}</style> \
	</head><body><h1>Backtrader Documentation</h1><p>Select language / 选择语言</p> \
	<a class="btn" href="en/index.html">English</a> \
	<a class="btn" href="zh/index_zh.html">中文</a> \
	<br><br><a class="btn gitee" href="https://gitee.com/yunjinqi/backtrader" target="_blank">Gitee</a> \
	<a class="btn" href="https://github.com/cloudQuant/backtrader" target="_blank">GitHub</a> \
	</body></html> \
	LANDING
	@echo "▶ Serving at http://localhost:8000"
	cd "$(BUILDDIR)/html" && python -m http.server 8000

# Build PDF
pdf:
	@echo "▶ Building PDF documentation..."
	$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)
	cd "$(BUILDDIR)/latex" && make
	@echo "✔ PDF → $(BUILDDIR)/latex/backtrader.pdf"

# Generate API documentation
apidoc:
	@echo "▶ Generating API documentation..."
	sphinx-apidoc -f -o "$(SOURCEDIR)/api" ../backtrader --separate
	@echo "✔ API docs → $(SOURCEDIR)/api"

# Check for broken links
linkcheck:
	@echo "▶ Checking links..."
	$(SPHINXBUILD) -b linkcheck "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck" $(SPHINXOPTS)
	@echo "✔ Results → $(BUILDDIR)/linkcheck/output.txt"

# Catch-all target: route all unknown targets to Sphinx
%: Makefile
	$(SPHINXBUILD) -b $@ "$(SOURCEDIR)" "$(BUILDDIR)/$@" $(SPHINXOPTS)
