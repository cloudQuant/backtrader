#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析 OKX 交易所上各交易对的最小交易资金要求。

这个脚本会：
1. 获取 OKX 所有交易对信息
2. 计算每个交易对的最小交易金额（USDT计价）
3. 按所需资金从少到多排序
4. 推荐适合小额测试的交易对
"""

import ccxt
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))


def fetch_okx_markets():
    """获取 OKX 市场信息"""
    print("正在连接 OKX 交易所...")
    exchange = ccxt.okx({
        'enableRateLimit': True,
    })

    print("正在加载市场数据...")
    markets = exchange.load_markets()
    return exchange, markets


def analyze_min_trading_amount(exchange, markets, base_currency='USDT'):
    """分析最小交易金额

    Args:
        exchange: CCXT 交易所实例
        markets: 市场信息字典
        base_currency: 基础货币，默认 USDT

    Returns:
        list: 包含每个交易对分析结果的列表
    """
    results = []

    print(f"\n正在分析 {base_currency} 交易对...")

    for symbol, market in markets.items():
        # 只分析 USDT 交易对
        if not market['quote'] == base_currency:
            continue

        # 只分析即期交易（spot）
        if market['type'] != 'spot':
            continue

        # 只分析活跃的交易对
        if not market['active']:
            continue

        try:
            # 获取当前价格
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            if current_price is None or current_price == 0:
                continue

            # 获取最小交易量限制
            limits = market['limits']
            min_amount = limits['amount']['min']  # 最小数量
            min_cost = limits['cost']['min']      # 最小金额（USDT）

            # 计算实际需要的最小资金
            # OKX 的最小交易额通常是 min_cost 和 (min_amount * price) 中的较大值
            if min_cost is not None and min_cost > 0:
                required_usdt = min_cost
            elif min_amount is not None and min_amount > 0:
                required_usdt = min_amount * current_price
            else:
                # 如果没有明确的限制，使用默认值
                required_usdt = 1.0  # 默认最小 1 USDT

            # 获取交易手续费等级
            # OKX 默认 maker fee: 0.08%, taker fee: 0.1%
            maker_fee = 0.0008  # 0.08%
            taker_fee = 0.001   # 0.1%

            result = {
                'symbol': symbol,
                'base': market['base'],      # 基础货币（如 BTC）
                'quote': market['quote'],    # 报价货币（USDT）
                'price': current_price,
                'min_amount': min_amount,
                'min_cost': min_cost,
                'required_usdt': required_usdt,
                'maker_fee': maker_fee,
                'taker_fee': taker_fee,
            }

            results.append(result)

        except Exception as e:
            # 跳过获取失败的交易对
            continue

    return results


def print_analysis_results(results, top_n=20):
    """打印分析结果

    Args:
        results: 分析结果列表
        top_n: 显示前 N 个结果
    """
    if not results:
        print("没有找到可用的交易对")
        return

    # 按所需 USDT 从小到大排序
    sorted_results = sorted(results, key=lambda x: x['required_usdt'])

    print(f"\n{'='*100}")
    print(f"OKX {results[0]['quote']} 交易对最小交易资金分析（共 {len(results)} 个交易对）")
    print(f"{'='*100}\n")

    # 打印表头
    print(f"{'排名':<5} {'交易对':<20} {'当前价格':<15} {'最小金额(USDT)':<18} {'可买数量':<15}")
    print(f"{'-'*100}")

    # 打印前 N 个
    for i, result in enumerate(sorted_results[:top_n], 1):
        symbol = result['symbol']
        price = result['price']
        required = result['required_usdt']

        # 计算可买入的数量
        buyable_amount = required / price

        print(f"{i:<5} {symbol:<20} ${price:<14.4f} ${required:<17.2f} {buyable_amount:<15.6f}")

    print(f"\n{'='*100}")

    # 统计信息
    min_required = sorted_results[0]['required_usdt']
    max_required = sorted_results[-1]['required_usdt']
    avg_required = sum(r['required_usdt'] for r in sorted_results) / len(sorted_results)

    print(f"\n统计信息:")
    print(f"  最小交易金额: ${min_required:.2f} USDT")
    print(f"  最大交易金额: ${max_required:.2f} USDT")
    print(f"  平均交易金额: ${avg_required:.2f} USDT")

    # 推荐适合小额测试的交易对（小于 10 USDT）
    print(f"\n推荐用于小额测试的交易对（< 10 USDT）:")
    small_trades = [r for r in sorted_results if r['required_usdt'] <= 10]
    if small_trades:
        for i, result in enumerate(small_trades[:10], 1):
            print(f"  {i}. {result['symbol']}: ${result['required_usdt']:.2f} USDT")
    else:
        print("  没有找到小于 10 USDT 的交易对")


def recommend_best_pairs(results, budget_usdt):
    """根据预算推荐最佳交易对

    Args:
        results: 分析结果列表
        budget_usdt: 用户预算（USDT）
    """
    sorted_results = sorted(results, key=lambda x: x['required_usdt'])

    print(f"\n{'='*100}")
    print(f"预算 ${budget_usdt} USDT 的推荐交易对")
    print(f"{'='*100}\n")

    # 找出符合预算的交易对
    affordable = [r for r in sorted_results if r['required_usdt'] <= budget_usdt]

    if not affordable:
        print(f"抱歉，预算 ${budget_usdt} USDT 不足以进行任何交易")
        print(f"最小需要 ${sorted_results[0]['required_usdt']:.2f} USDT")
        return

    print(f"共有 {len(affordable)} 个交易对符合您的预算\n")

    # 推荐策略：选择交易量大、价格稳定的币种
    # 这里简单推荐前几个
    print("推荐交易对（按资金需求排序）:")
    print(f"{'排名':<5} {'交易对':<20} {'所需金额':<15} {'可买次数':<15} {'建议用途'}")
    print(f"{'-'*100}")

    for i, result in enumerate(affordable[:10], 1):
        trades_possible = int(budget_usdt / result['required_usdt'])
        symbol = result['symbol']
        required = result['required_usdt']

        # 根据币种给出建议
        base = result['base']
        if base in ['BTC', 'ETH']:
            usage = "主流币，适合长期持有"
        elif base in ['SOL', 'ADA', 'DOT', 'AVAX']:
            usage = "热门公链币，波动适中"
        elif base in['DOGE', 'SHIB', 'PEPE']:
            usage = "Meme币，波动大，谨慎"
        else:
            usage = "适合测试和练习"

        print(f"{i:<5} {symbol:<20} ${required:<14.2f} {trades_possible:<15} {usage}")


def main():
    """主函数"""
    try:
        # 获取市场数据
        exchange, markets = fetch_okx_markets()

        # 分析 USDT 交易对
        results = analyze_min_trading_amount(exchange, markets, 'USDT')

        # 打印分析结果
        print_analysis_results(results, top_n=30)

        # 分析不同预算范围
        budgets = [1, 5, 10, 20, 50, 100]
        print(f"\n{'='*100}")
        print("不同预算可交易的交易对数量:")
        print(f"{'='*100}\n")

        for budget in budgets:
            affordable = len([r for r in results if r['required_usdt'] <= budget])
            print(f"  预算 ${budget:3d} USDT: 可交易 {affordable:3d} 个交易对")

        # 额外分析：低价格币种（适合小资金）
        print(f"\n{'='*100}")
        print("低价格币种推荐（价格 < $0.1，可以用很少的资金买很多数量）:")
        print(f"{'='*100}\n")

        low_price = [r for r in results if r['price'] < 0.1]
        low_price_sorted = sorted(low_price, key=lambda x: x['price'])

        print(f"{'排名':<5} {'交易对':<20} {'价格':<15} {'$1可买数量':<15} {'$10可买数量':<15}")
        print(f"{'-'*100}")

        for i, result in enumerate(low_price_sorted[:15], 1):
            price = result['price']
            buy_1_usdt = 1.0 / price
            buy_10_usdt = 10.0 / price

            print(f"{i:<5} {result['symbol']:<20} ${price:<14.6f} {buy_1_usdt:<15.2f} {buy_10_usdt:<15.2f}")

        print(f"\n{'='*100}")
        print("分析完成！")
        print(f"{'='*100}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
