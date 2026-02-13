#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX 配置检查工具.

这个脚本会检查：
1. API 密钥配置是否正确
2. 账户余额是否充足
3. DOGS/USDT 合约是否可用
4. 最小交易金额要求
5. 模拟下单测试
"""

import sys
from pathlib import Path
import ccxt

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from backtrader.ccxt import load_ccxt_config_from_env


def check_api_config():
    """检查 API 配置"""
    print("=" * 80)
    print("1. Check API Configuration")
    print("=" * 80)

    try:
        config = load_ccxt_config_from_env('okx')
        print("[OK] API keys loaded successfully")
        print(f"  - apiKey: {'*' * 20}{config.get('apiKey', '')[-4:]}")
        print(f"  - secret: {'*' * 20}{config.get('secret', '')[-4:]}")
        print(f"  - password: {'*' * 20}{config.get('password', '')[-4:]}")
        return config
    except Exception as e:
        print(f"[FAIL] API configuration failed: {e}")
        print("\nPlease configure in .env file:")
        print("OKX_API_KEY=your_api_key")
        print("OKX_SECRET=your_secret")
        print("OKX_PASSWORD=your_password")
        return None


def check_api_connection(config):
    """检查 API 连接"""
    print("\n" + "=" * 80)
    print("2. 检查 API 连接")
    print("=" * 80)

    try:
        exchange = ccxt.okx(config)

        # 测试获取账户余额
        balance = exchange.fetch_balance()
        print("✓ API 连接成功")

        # 检查 USDT 余额
        if 'USDT' in balance['total']:
            usdt_balance = balance['total']['USDT']
            usdt_free = balance['free']['USDT']
            usdt_used = balance['used']['USDT']
            print(f"  - USDT 总额: {usdt_balance:.2f}")
            print(f"  - USDT 可用: {usdt_free:.2f}")
            print(f"  - USDT 冻结: {usdt_used:.2f}")

            # 检查合约账户
            if 'USDT:USDT' in balance.get('total', {}):
                swap_balance = balance['total']['USDT:USDT']
                print(f"  - 合约账户余额: {swap_balance:.2f} USDT")
        else:
            print("  ⚠ 未找到 USDT 余额")

        return exchange, balance

    except Exception as e:
        print(f"✗ API 连接失败: {e}")
        return None, None


def check_dogs_swap_market(exchange):
    """检查 DOGS/USDT 永续合约市场"""
    print("\n" + "=" * 80)
    print("3. 检查 DOGS/USDT 永续合约")
    print("=" * 80)

    try:
        # 加载市场
        markets = exchange.load_markets()

        # 检查 DOGS/USDT:USDT (永续合约)
        symbol = 'DOGS/USDT:USDT'

        if symbol not in markets:
            print(f"✗ 未找到 {symbol} 交易对")
            print("\n可用的 DOGS 交易对:")
            dogs_pairs = [s for s in markets.keys() if 'DOGS' in s]
            for pair in dogs_pairs:
                print(f"  - {pair}")
            return False

        market = markets[symbol]
        print(f"✓ 找到 {symbol} 永续合约")

        # 获取交易对信息
        print(f"  - 基础货币: {market['base']}")
        print(f"  - 报价货币: {market['quote']}")
        print(f"  - 类型: {market['type']}")
        print(f"  - 活跃: {market['active']}")

        # 获取当前价格
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        print(f"  - 当前价格: ${current_price:.6f}")

        # 获取交易限制
        limits = market['limits']
        min_amount = limits['amount']['min']
        min_cost = limits['cost']['min']

        print(f"\n交易限制:")
        print(f"  - 最小数量: {min_amount}")
        print(f"  - 最小金额: ${min_cost}")

        # 计算 0.4 USDT 可买入的数量
        order_size = 0.4  # USDT
        buy_amount = order_size / current_price
        print(f"\n下单测试:")
        print(f"  - 下单金额: ${order_size} USDT")
        print(f"  - 可买数量: {buy_amount:.2f} DOGS")

        # 检查是否满足最小交易要求
        if buy_amount >= min_amount:
            print(f"  ✓ 满足最小交易要求 (>= {min_amount})")
        else:
            print(f"  ✗ 不满足最小交易要求 (需要 >= {min_amount})")

        # 计算手续费
        maker_fee = 0.0002  # OKX 合约 maker 费率
        taker_fee = 0.0005  # OKX 合约 taker 费率
        fee_maker = order_size * maker_fee
        fee_taker = order_size * taker_fee

        print(f"\n手续费估算:")
        print(f"  - Maker 费率: 0.02%")
        print(f"  - Taker 费率: 0.05%")
        print(f"  - Maker 手续费: ${fee_maker:.6f} USDT")
        print(f"  - Taker 手续费: ${fee_taker:.6f} USDT")
        print(f"  - 手续费占比: {(fee_taker / order_size * 100):.2f}%")

        return True, market, current_price, buy_amount

    except Exception as e:
        print(f"✗ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False, None, None, None


def check_sandbox_mode():
    """建议使用沙盒模式测试"""
    print("\n" + "=" * 80)
    print("4. 测试环境建议")
    print("=" * 80)

    print("\n⚠️  重要提示:")
    print("建议先在以下环境测试策略：")
    print("\n1. OKX 沙盒环境（测试网）:")
    print("   - 网址: https://www.okx.com/demo-trading")
    print("   - 提供测试 API 密钥")
    print("   - 不使用真实资金")

    print("\n2. 回测模式:")
    print("   - 使用历史数据测试")
    print("   - 不需要连接交易所")

    print("\n3. 小额实盘:")
    print("   - 使用最小金额（0.4 USDT）")
    print("   - 验证策略逻辑")


def print_summary(config_ok, connection_ok, market_ok):
    """打印总结"""
    print("\n" + "=" * 80)
    print("检查总结")
    print("=" * 80)

    checks = [
        ("API 配置", config_ok),
        ("API 连接", connection_ok),
        ("DOGS/USDT 合约", market_ok),
    ]

    all_ok = True
    for name, status in checks:
        if status:
            print(f"✓ {name}: 正常")
        else:
            print(f"✗ {name}: 失败")
            all_ok = False

    print("\n" + "=" * 80)

    if all_ok:
        print("✓ 所有检查通过！可以运行策略了")
        print("\n运行命令:")
        print("python examples/backtrader_ccxt_okx_dogs_bollinger.py")
    else:
        print("✗ 部分检查失败，请先解决上述问题")

    print("=" * 80)


def main():
    """主函数"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "OKX DOGS/USDT 策略配置检查" + " " * 28 + "║")
    print("╚" + "=" * 78 + "╝")

    # 1. 检查 API 配置
    config = check_api_config()
    config_ok = config is not None

    # 2. 检查 API 连接
    if config_ok:
        exchange, balance = check_api_connection(config)
        connection_ok = exchange is not None
    else:
        exchange, balance = None, None
        connection_ok = False

    # 3. 检查 DOGS/USDT 合约
    if connection_ok:
        market_ok, market, price, amount = check_dogs_swap_market(exchange)
    else:
        market_ok = False

    # 4. 测试环境建议
    check_sandbox_mode()

    # 5. 打印总结
    print_summary(config_ok, connection_ok, market_ok)


if __name__ == '__main__':
    main()
