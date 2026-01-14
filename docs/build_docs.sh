#!/bin/bash
# Backtrader Documentation Build Script
# 
# Usage:
#   ./build_docs.sh          # Build both English and Chinese
#   ./build_docs.sh en       # Build English only
#   ./build_docs.sh zh       # Build Chinese only
#   ./build_docs.sh clean    # Clean build directory
#   ./build_docs.sh serve    # Build and start local server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check dependencies
check_dependencies() {
    echo_info "Checking dependencies..."
    
    if ! command -v sphinx-build &> /dev/null; then
        echo_error "sphinx-build not found. Installing Sphinx..."
        pip install sphinx sphinx-copybutton furo sphinx-autobuild
    fi
    
    echo_info "Dependencies OK"
}

# Build English documentation
build_en() {
    echo_info "Building English documentation..."
    sphinx-build -b html source _build/html/en
    echo_info "English documentation built at _build/html/en/index.html"
}

# Build Chinese documentation
build_zh() {
    echo_info "Building Chinese documentation..."
    sphinx-build -b html source _build/html/zh -D language=zh_CN -D master_doc=index_zh
    echo_info "Chinese documentation built at _build/html/zh/index.html"
}

# Clean build directory
clean() {
    echo_info "Cleaning build directory..."
    rm -rf _build
    echo_info "Build directory cleaned"
}

# Generate API documentation
apidoc() {
    echo_info "Generating API documentation..."
    sphinx-apidoc -f -o source/api ../backtrader --separate \
        --no-toc \
        -H "Backtrader API" \
        -A "Backtrader Contributors"
    echo_info "API documentation generated"
}

# Start local server
serve() {
    echo_info "Starting documentation server..."
    
    # Build first
    build_en
    build_zh
    
    # Create index page
    cat > _build/html/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Backtrader Documentation</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
               max-width: 600px; margin: 100px auto; text-align: center; }
        h1 { color: #2962FF; }
        .links { margin-top: 40px; }
        .links a { display: inline-block; margin: 10px 20px; padding: 15px 40px;
                   background: #2962FF; color: white; text-decoration: none;
                   border-radius: 8px; font-size: 18px; }
        .links a:hover { background: #1E4FD6; }
    </style>
</head>
<body>
    <h1>Backtrader Documentation</h1>
    <p>Select your preferred language:</p>
    <div class="links">
        <a href="en/index.html">English</a>
        <a href="zh/index_zh.html">中文</a>
    </div>
</body>
</html>
EOF
    
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
    serve)
        check_dependencies
        serve
        ;;
    *)
        echo "Usage: $0 {en|zh|all|clean|apidoc|serve}"
        exit 1
        ;;
esac

echo_info "Done!"
