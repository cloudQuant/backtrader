#!/bin/bash
# Backtrader 代码优化脚本
# 使用 pyupgrade, ruff 等工具优化代码风格和格式

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "Backtrader 代码优化工具"
echo "=========================================="
echo ""

# 检查必要的工具
check_tool() {
    if ! command -v $1 &> /dev/null; then
        echo "❌ 错误: 未找到 $1"
        echo "请运行: pip install $2"
        exit 1
    fi
}

echo "📋 检查依赖工具..."
check_tool "python" "python3"
python -m pip list | grep -q "pyupgrade" || (echo "❌ 缺少 pyupgrade"; exit 1)
python -m pip list | grep -q "ruff" || (echo "❌ 缺少 ruff"; exit 1)
echo "✅ 所有依赖工具已安装"
echo ""

# 步骤 1: 使用 pyupgrade 升级 Python 语法
echo "🔧 步骤 1: 使用 pyupgrade 升级 Python 语法..."
python -m pyupgrade --py311-plus backtrader/**/*.py --exit-zero-even-if-changed
echo "✅ pyupgrade 完成"
echo ""

# 步骤 2: 使用 ruff 格式化代码
echo "🔧 步骤 2: 使用 ruff 格式化代码..."
python -m ruff format backtrader/ --line-length 100
echo "✅ ruff format 完成"
echo ""

# 步骤 3: 使用 ruff 进行 linting 并自动修复
echo "🔧 步骤 3: 使用 ruff 进行 linting 并自动修复..."
python -m ruff check backtrader/ --fix
echo "✅ ruff check 完成"
echo ""

# 步骤 4: 运行测试验证
echo "🧪 步骤 4: 运行测试验证代码完整性..."
if [ -d "tests/add_tests" ]; then
    python -m pytest tests/add_tests/ -x --tb=short -q
    echo "✅ 所有测试通过"
else
    echo "⚠️  未找到测试目录"
fi
echo ""

echo "=========================================="
echo "✅ 代码优化完成！"
echo "=========================================="
