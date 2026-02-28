#!/bin/bash

# Markdown 格式清理脚本 (Shell 包装器)
# 用于修复项目中 Markdown 文件的格式问题

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示帮助信息
show_help() {
    echo "Markdown 格式清理工具"
    echo ""
    echo "用法: $0 [选项] [路径]"
    echo ""
    echo "选项:"
    echo "  --help              显示此帮助信息"
    echo "  --dry-run           试运行模式，只检查不修改文件"
    echo "  --check             检查项目中的 Markdown 文件格式"
    echo "  --fix               修复项目中的 Markdown 文件格式"
    echo "  --docs              只处理 docs 目录"
    echo "  --root              只处理根目录的 Markdown 文件"
    echo ""
    echo "路径:"
    echo "  如果不指定路径，默认处理当前目录"
    echo ""
    echo "示例:"
    echo "  $0 --check                    # 检查所有 Markdown 文件"
    echo "  $0 --fix                      # 修复所有 Markdown 文件"
    echo "  $0 --dry-run                  # 试运行模式"
    echo "  $0 --docs                     # 只处理 docs 目录"
    echo "  $0 README.md                  # 处理单个文件"
}

# 检查 Python 环境
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装，请先安装 Python3"
        exit 1
    fi
    
    log_success "Python3 环境检查通过"
}

# 获取脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/clean_markdown.py"

# 检查 Python 脚本是否存在
if [ ! -f "$PYTHON_SCRIPT" ]; then
    log_error "Python 脚本不存在: $PYTHON_SCRIPT"
    exit 1
fi

# 主函数
main() {
    local dry_run=false
    local check_only=false
    local fix_mode=false
    local docs_only=false
    local root_only=false
    local target_path=""
    
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help)
                show_help
                exit 0
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --check)
                check_only=true
                dry_run=true
                shift
                ;;
            --fix)
                fix_mode=true
                shift
                ;;
            --docs)
                docs_only=true
                target_path="$PROJECT_ROOT/docs"
                shift
                ;;
            --root)
                root_only=true
                target_path="$PROJECT_ROOT"
                shift
                ;;
            -*)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
            *)
                target_path="$1"
                shift
                ;;
        esac
    done
    
    echo -e "${BLUE}"
    echo "========================================"
    echo "    Markdown 格式清理工具"
    echo "========================================"
    echo -e "${NC}"
    
    # 检查 Python 环境
    check_python
    
    # 设置默认路径
    if [ -z "$target_path" ]; then
        target_path="$PROJECT_ROOT"
    fi
    
    # 转换为绝对路径
    if [ ! -d "$target_path" ] && [ ! -f "$target_path" ]; then
        # 如果不是绝对路径，尝试相对于项目根目录
        if [[ "$target_path" != /* ]]; then
            target_path="$PROJECT_ROOT/$target_path"
        fi
    fi
    
    # 检查路径是否存在
    if [ ! -e "$target_path" ]; then
        log_error "路径不存在: $target_path"
        exit 1
    fi
    
    # 构建 Python 命令
    local python_args=()
    
    if [ "$dry_run" = true ]; then
        python_args+=("--dry-run")
    fi
    
    python_args+=("$target_path")
    
    # 显示操作信息
    if [ "$check_only" = true ]; then
        log_info "检查 Markdown 文件格式..."
    elif [ "$dry_run" = true ]; then
        log_info "试运行模式 - 不会修改文件..."
    else
        log_info "修复 Markdown 文件格式..."
    fi
    
    if [ "$docs_only" = true ]; then
        log_info "目标: docs 目录"
    elif [ "$root_only" = true ]; then
        log_info "目标: 项目根目录"
    else
        log_info "目标: $target_path"
    fi
    
    echo ""
    
    # 执行 Python 脚本
    cd "$PROJECT_ROOT"
    
    # 首先运行我们的基础清理
    if python3 "$PYTHON_SCRIPT" "${python_args[@]}"; then
        # 如果不是试运行模式，再运行 markdownlint 修复
        if [ "$dry_run" = false ] && command -v markdownlint &> /dev/null; then
            log_info "运行 markdownlint 深度修复..."
            if python3 "$SCRIPT_DIR/fix_markdownlint.py" "$target_path" > /dev/null 2>&1; then
                log_success "markdownlint 修复完成"
            else
                log_warning "markdownlint 修复遇到问题，但基础清理已完成"
            fi
        fi
        echo ""
        if [ "$check_only" = true ]; then
            log_success "Markdown 格式检查完成"
        elif [ "$dry_run" = true ]; then
            log_success "试运行完成"
        else
            log_success "Markdown 格式修复完成"
        fi
    else
        echo ""
        log_error "操作失败"
        exit 1
    fi
}

# 执行主函数
main "$@"