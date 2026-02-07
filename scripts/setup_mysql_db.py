#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Setup script for backtrader TradeLogger MySQL database.

Creates the ``backtrder_web`` database and the required tables
(bt_order_log, bt_trade_log, bt_position_log) for persisting
backtest logs from TradeLogger.

Usage::

    python scripts/setup_mysql_db.py

The script will prompt for the MySQL root password.
Press Enter to use the default password (backtrader_web_123).
"""

import getpass
import sys


def get_password():
    """Prompt user for MySQL root password with a default fallback."""
    print("=" * 60)
    print("  Backtrader TradeLogger - MySQL Database Setup")
    print("=" * 60)
    print()
    print("This script will create:")
    print("  - Database: backtrder_web")
    print("  - Table:    bt_order_log")
    print("  - Table:    bt_trade_log")
    print("  - Table:    bt_position_log")
    print()
    pwd = getpass.getpass(
        "Enter MySQL root password (press Enter for default 'backtrader_web_123'): "
    )
    if not pwd:
        pwd = "backtrader_web_123"
    return pwd


def create_database(cursor, db_name):
    """Create the database if it does not exist."""
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.execute(f"USE `{db_name}`")


def create_tables(cursor, prefix="bt"):
    """Create the three log tables with best-practice schema."""

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `{prefix}_order_log` (
            `id`              BIGINT AUTO_INCREMENT PRIMARY KEY,
            `log_time`        DATETIME(6)  COMMENT 'wall-clock time when this record was written',
            `run_id`          VARCHAR(128) NOT NULL,
            `strategy_name`   VARCHAR(128) NOT NULL,
            `strategy_params` TEXT,
            `run_datetime`    DATETIME     COMMENT 'when the backtest run started',
            `ref`             INT,
            `ordtype`         VARCHAR(32),
            `status`          VARCHAR(32),
            `size`            DOUBLE,
            `price`           DOUBLE,
            `exectype`        VARCHAR(32),
            `executed_price`  DOUBLE,
            `executed_size`   DOUBLE,
            `commission`      DOUBLE,
            `dt`              DATETIME     COMMENT 'bar datetime of the order event',
            `data_name`       VARCHAR(256),
            `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_run_id`          (`run_id`),
            INDEX `idx_strategy_run`    (`strategy_name`, `run_id`),
            INDEX `idx_run_datetime`    (`run_datetime`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `{prefix}_trade_log` (
            `id`              BIGINT AUTO_INCREMENT PRIMARY KEY,
            `log_time`        DATETIME(6)  COMMENT 'wall-clock time when this record was written',
            `run_id`          VARCHAR(128) NOT NULL,
            `strategy_name`   VARCHAR(128) NOT NULL,
            `strategy_params` TEXT,
            `run_datetime`    DATETIME     COMMENT 'when the backtest run started',
            `ref`             INT,
            `status`          VARCHAR(32),
            `size`            DOUBLE,
            `price`           DOUBLE,
            `value`           DOUBLE,
            `commission`      DOUBLE,
            `pnl`             DOUBLE,
            `pnlcomm`         DOUBLE,
            `isopen`          TINYINT(1),
            `isclosed`        TINYINT(1),
            `justopened`      TINYINT(1),
            `baropen`         INT,
            `barclose`        INT,
            `barlen`          INT,
            `dtopen`          DATETIME,
            `dtclose`         DATETIME,
            `data_name`       VARCHAR(256),
            `tradeid`         INT,
            `is_long`         TINYINT(1),
            `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_run_id`          (`run_id`),
            INDEX `idx_strategy_run`    (`strategy_name`, `run_id`),
            INDEX `idx_run_datetime`    (`run_datetime`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `{prefix}_position_log` (
            `id`              BIGINT AUTO_INCREMENT PRIMARY KEY,
            `log_time`        DATETIME(6)  COMMENT 'wall-clock time when this record was written',
            `run_id`          VARCHAR(128) NOT NULL,
            `strategy_name`   VARCHAR(128) NOT NULL,
            `strategy_params` TEXT,
            `run_datetime`    DATETIME     COMMENT 'when the backtest run started',
            `dt`              DATETIME     COMMENT 'bar datetime of the position snapshot',
            `data_name`       VARCHAR(256),
            `size`            DOUBLE,
            `price`           DOUBLE,
            `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_run_id`          (`run_id`),
            INDEX `idx_strategy_run`    (`strategy_name`, `run_id`),
            INDEX `idx_run_datetime`    (`run_datetime`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def main():
    try:
        import pymysql
    except ImportError:
        print("ERROR: pymysql is not installed.")
        print("Install with:  pip install pymysql")
        sys.exit(1)

    # Accept password from command line or prompt interactively
    if len(sys.argv) > 1:
        password = sys.argv[1]
        print("=" * 60)
        print("  Backtrader TradeLogger - MySQL Database Setup")
        print("=" * 60)
        print()
        print("This script will create:")
        print("  - Database: backtrder_web")
        print("  - Table:    bt_order_log")
        print("  - Table:    bt_trade_log")
        print("  - Table:    bt_position_log")
        print()
        print("Using password from command line argument.")
    else:
        password = get_password()
    db_name = "backtrder_web"
    prefix = "bt"

    print()
    print(f"Connecting to MySQL as root@localhost ...")

    try:
        conn = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password=password,
            charset="utf8mb4",
        )
    except Exception as e:
        print(f"\nERROR: Failed to connect to MySQL: {e}")
        sys.exit(1)

    try:
        cursor = conn.cursor()

        print(f"Creating database `{db_name}` ...")
        create_database(cursor, db_name)

        print(f"Creating tables with prefix `{prefix}_` ...")
        create_tables(cursor, prefix)

        conn.commit()
        cursor.close()

        print()
        print("=" * 60)
        print("  SUCCESS!")
        print(f"  Database `{db_name}` and tables created successfully.")
        print()
        print("  Tables created:")
        print(f"    - {prefix}_order_log")
        print(f"    - {prefix}_trade_log")
        print(f"    - {prefix}_position_log")
        print("=" * 60)

    except Exception as e:
        print()
        print("=" * 60)
        print(f"  FAILED: {e}")
        print("=" * 60)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
