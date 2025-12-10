#!/usr/bin/env python
"""
数据清洗脚本：从bond_merged_all_data.csv中找出可交易天数最多的可转债
"""
import pandas as pd


def find_most_traded_bond():
    """找出可交易天数最多的可转债并保存"""
    # 读取数据
    print("正在读取数据...")
    df = pd.read_csv("bond_merged_all_data.csv")

    # 打印列名以便确认
    print(f"数据列名: {df.columns.tolist()}")
    print(f"总数据行数: {len(df)}")

    # 按照可转债代码分组，统计每个可转债的交易天数
    bond_counts = df.groupby("BOND_CODE").size()

    # 找出交易天数最多的可转债
    most_traded_bond = bond_counts.idxmax()
    max_trading_days = bond_counts.max()

    print(f"\n交易天数最多的可转债代码: {most_traded_bond}")
    print(f"交易天数: {max_trading_days}")

    # 获取该可转债的所有数据
    bond_data = df[df["BOND_CODE"] == most_traded_bond].copy()

    # 获取可转债名称（从BOND_SYMBOL列获取，去掉交易所前缀）
    bond_symbol = bond_data["BOND_SYMBOL"].iloc[0]
    # 例如 'sh110002' -> '110002'
    bond_name = bond_symbol.replace("sh", "").replace("sz", "")

    print(f"可转债名称: {bond_name}")
    print(f"数据日期范围: {bond_data['TRADE_DATE'].min()} 到 {bond_data['TRADE_DATE'].max()}")

    # 保存为CSV文件，以可转债代码命名
    output_file = f"{bond_name}.csv"
    bond_data.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n数据已保存到文件: {output_file}")

    # 打印前几行数据预览
    print("\n数据预览:")
    print(bond_data.head())

    return bond_name, bond_data


if __name__ == "__main__":
    bond_name, bond_data = find_most_traded_bond()
