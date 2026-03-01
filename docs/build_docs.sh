#!/bin/bash
# Backtrader Documentation Build Script
#
# Usage:
#   ./build_docs.sh              Build both English and Chinese
#   ./build_docs.sh en           Build English only
#   ./build_docs.sh zh           Build Chinese only
#   ./build_docs.sh clean        Clean build directory
#   ./build_docs.sh serve        Build and start local server
#   ./build_docs.sh apidoc       Generate API documentation
#   ./build_docs.sh linkcheck    Check for broken links
#   ./build_docs.sh install      Install documentation dependencies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info()  { echo -e "${GREEN}[✔]${NC} $1"; }
echo_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[✘]${NC} $1"; }
echo_step()  { echo -e "${BLUE}[▶]${NC} $1"; }

# Check / install dependencies
check_dependencies() {
    echo_step "Checking dependencies..."
    if ! command -v sphinx-build &> /dev/null; then
        echo_warn "sphinx-build not found. Installing from requirements.txt..."
        pip install -r requirements.txt
    fi
    echo_info "Dependencies OK"
}

install_deps() {
    echo_step "Installing documentation dependencies..."
    pip install -r requirements.txt
    echo_info "Dependencies installed"
}

# Build English documentation
build_en() {
    echo_step "Building English documentation..."
    sphinx-build -b html source _build/html/en -j auto
    echo_info "English docs → _build/html/en/index.html"
}

# Build Chinese documentation
build_zh() {
    echo_step "Building Chinese documentation..."
    sphinx-build -b html source _build/html/zh \
        -D language=zh_CN -D root_doc=index_zh -D master_doc=index_zh -j auto
    echo_info "Chinese docs → _build/html/zh/index_zh.html"
}

clean() {
    echo_step "Cleaning build directory..."
    rm -rf _build
    echo_info "Build directory cleaned"
}

apidoc() {
    echo_step "Generating API documentation..."
    sphinx-apidoc -f -o source/api ../backtrader --separate \
        --no-toc -H "Backtrader API" -A "Backtrader Contributors"
    echo_info "API documentation generated → source/api/"
}

linkcheck() {
    echo_step "Checking for broken links..."
    sphinx-build -b linkcheck source _build/linkcheck -j auto
    echo_info "Results → _build/linkcheck/output.txt"
}

# Create language landing page
create_landing_page() {
    cat > _build/html/index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Backtrader Documentation</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 50%, #E8EAF6 100%);
            padding: 20px;
        }
        .card {
            background: #fff; border-radius: 16px; padding: 48px 40px;
            box-shadow: 0 8px 32px rgba(21,101,192,0.12);
            text-align: center; max-width: 520px; width: 100%;
        }
        h1 { color: #1565C0; font-size: 2rem; margin-bottom: 8px; }
        p { color: #546E7A; margin-bottom: 28px; font-size: 1.05rem; }
        .lang-buttons { display: flex; gap: 16px; justify-content: center; margin-bottom: 24px; }
        .btn {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 14px 36px; border-radius: 10px; font-size: 1rem; font-weight: 600;
            text-decoration: none; transition: transform 0.15s, box-shadow 0.15s;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.15); }
        .btn-en { background: #1565C0; color: #fff; }
        .btn-zh { background: #C71D23; color: #fff; }
        .repo-links { display: flex; gap: 12px; justify-content: center; }
        .repo-links a {
            padding: 8px 20px; border-radius: 8px; font-size: 0.9rem; font-weight: 500;
            text-decoration: none; border: 1px solid #B0BEC5; color: #37474F;
            transition: background 0.15s;
        }
        .repo-links a:hover { background: #ECEFF1; }
    </style>
</head>
<body>
    <div class="card">
        <h1>📈 Backtrader</h1>
        <p>Select language / 选择语言</p>
        <div class="lang-buttons">
            <a class="btn btn-en" href="en/index.html">English</a>
            <a class="btn btn-zh" href="zh/index_zh.html">中文</a>
        </div>
        <div class="repo-links">
            <a href="https://github.com/cloudQuant/backtrader" target="_blank">⭐ GitHub</a>
            <a href="https://gitee.com/yunjinqi/backtrader" target="_blank">🇨🇳 Gitee</a>
        </div>
    </div>
</body>
</html>
EOF
}

serve() {
    echo_step "Building all documentation..."
    build_en
    build_zh
    create_landing_page
    echo ""
    echo_info "Documentation server starting at http://localhost:8000"
    echo_info "Press Ctrl+C to stop"
    cd _build/html && python -m http.server 8000
}

# Main
case "${1:-all}" in
    en)
        check_dependencies
        build_en
        ;;
    zh)
        check_dependencies
        build_zh
        ;;
    all)
        check_dependencies
        build_en
        build_zh
        ;;
    clean)
        clean
        ;;
    apidoc)
        check_dependencies
        apidoc
        ;;
    linkcheck)
        check_dependencies
        linkcheck
        ;;
    serve)
        check_dependencies
        serve
        ;;
    install)
        install_deps
        ;;
    *)
        echo "Usage: $0 {en|zh|all|clean|apidoc|linkcheck|serve|install}"
        exit 1
        ;;
esac

echo_info "Done!"
