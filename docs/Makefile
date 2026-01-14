# Makefile for Sphinx documentation
#
# You can set these variables from the command line.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SPHINXINTL    ?= sphinx-intl
SOURCEDIR     = source
BUILDDIR      = _build
LOCALEDIR     = source/locales

# Put it first so that "make" without argument is like "make help".
help:
	@echo "Backtrader Documentation Build System"
	@echo ""
	@echo "Available targets:"
	@echo "  html        Build English HTML documentation"
	@echo "  html-zh     Build Chinese HTML documentation"
	@echo "  html-all    Build both English and Chinese documentation"
	@echo "  gettext     Extract translatable strings"
	@echo "  update-po   Update translation files"
	@echo "  clean       Remove build directory"
	@echo "  livehtml    Start live reload server (English)"
	@echo "  pdf         Build PDF documentation"
	@echo "  apidoc      Generate API documentation from source code"
	@echo ""

.PHONY: help Makefile html html-zh html-all gettext update-po clean livehtml pdf apidoc

# Build English HTML
html:
	@echo "Building English documentation..."
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html/en" $(SPHINXOPTS)
	@echo ""
	@echo "English documentation built at $(BUILDDIR)/html/en/index.html"

# Build Chinese HTML
html-zh:
	@echo "Building Chinese documentation..."
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html/zh" -D language=zh_CN $(SPHINXOPTS)
	@echo ""
	@echo "Chinese documentation built at $(BUILDDIR)/html/zh/index.html"

# Build both languages
html-all: html html-zh
	@echo ""
	@echo "All documentation built successfully!"
	@echo "  English: $(BUILDDIR)/html/en/index.html"
	@echo "  Chinese: $(BUILDDIR)/html/zh/index.html"

# Extract translatable strings
gettext:
	@echo "Extracting translatable strings..."
	$(SPHINXBUILD) -b gettext "$(SOURCEDIR)" "$(BUILDDIR)/gettext" $(SPHINXOPTS)
	@echo ""
	@echo "Gettext files created at $(BUILDDIR)/gettext"

# Update translation files
update-po: gettext
	@echo "Updating translation files..."
	$(SPHINXINTL) update -p "$(BUILDDIR)/gettext" -l zh_CN -d "$(LOCALEDIR)"
	@echo ""
	@echo "Translation files updated at $(LOCALEDIR)/zh_CN/LC_MESSAGES"

# Clean build directory
clean:
	rm -rf "$(BUILDDIR)"
	@echo "Build directory cleaned."

# Live reload server for development
livehtml:
	@echo "Starting live reload server..."
	sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html/en" $(SPHINXOPTS)

# Build PDF
pdf:
	@echo "Building PDF documentation..."
	$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)
	cd "$(BUILDDIR)/latex" && make
	@echo ""
	@echo "PDF built at $(BUILDDIR)/latex/backtrader.pdf"

# Generate API documentation
apidoc:
	@echo "Generating API documentation..."
	sphinx-apidoc -f -o "$(SOURCEDIR)/api" ../backtrader --separate
	@echo ""
	@echo "API documentation generated at $(SOURCEDIR)/api"

# Catch-all target: route all unknown targets to Sphinx
%: Makefile
	$(SPHINXBUILD) -b $@ "$(SOURCEDIR)" "$(BUILDDIR)/$@" $(SPHINXOPTS)
