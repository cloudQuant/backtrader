#!/usr/bin/env python
"""
Data cleaning script: Find the convertible bond with most trading days from bond_merged_all_data.csv
"""
import pandas as pd


def find_most_traded_bond():
    """Find the convertible bond with most trading days and save it"""
    # Read data
    print("Reading data...")
    df = pd.read_csv("bond_merged_all_data.csv")

    # Print column names for confirmation
    print(f"Data columns: {df.columns.tolist()}")
    print(f"Total data rows: {len(df)}")

    # Group by convertible bond code, count trading days for each bond
    bond_counts = df.groupby("BOND_CODE").size()

    # Find the convertible bond with most trading days
    most_traded_bond = bond_counts.idxmax()
    max_trading_days = bond_counts.max()

    print(f"\nConvertible bond code with most trading days: {most_traded_bond}")
    print(f"Trading days: {max_trading_days}")

    # Get all data for this convertible bond
    bond_data = df[df["BOND_CODE"] == most_traded_bond].copy()

    # Get convertible bond name (from BOND_SYMBOL column, remove exchange prefix)
    bond_symbol = bond_data["BOND_SYMBOL"].iloc[0]
    # For example 'sh110002' -> '110002'
    bond_name = bond_symbol.replace("sh", "").replace("sz", "")

    print(f"Convertible bond name: {bond_name}")
    print(f"Data date range: {bond_data['TRADE_DATE'].min()} to {bond_data['TRADE_DATE'].max()}")

    # Save as CSV file, named after convertible bond code
    output_file = f"{bond_name}.csv"
    bond_data.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\nData saved to file: {output_file}")

    # Print data preview
    print("\nData preview:")
    print(bond_data.head())

    return bond_name, bond_data


if __name__ == "__main__":
    bond_name, bond_data = find_most_traded_bond()
