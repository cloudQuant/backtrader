#!/usr/bin/env python
"""TradeLogger Observer Module - Comprehensive trade and data logging.

This module provides the TradeLogger observer for recording order, trade,
position, and bar data (OHLCV + open interest + custom fields + strategy
indicators) during backtesting.

Logs are written to files **in real-time** (appended on every bar) so that
data is available even if the process crashes.  A ``current_position.json``
file is updated after every bar with the latest position snapshot.

At the end of the run, logs are optionally batch-inserted into **MySQL**.

Each run is tagged with a unique ``run_id`` composed of strategy name and
timestamp, so results from the same strategy with different parameters or
run times are stored separately.

File output layout (when ``log_file_enabled=True``)::

    {log_dir}/{StrategyName}_{YYYYMMDD_HHMMSS}/
        run_info.json           # metadata
        current_position.json   # latest position (overwritten each bar)
        order.{ext}
        trade.{ext}
        position.{ext}
        data.{ext}

``{ext}`` is ``log`` (default, tab-separated) or ``csv`` depending on
the ``file_format`` parameter.

MySQL tables (when ``mysql_enabled=True``) – only order, trade, and
position logs are persisted to MySQL (data logs are file-only)::

    {prefix}_order
    {prefix}_trade
    {prefix}_position

Example::

    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir='logs',
        file_format='log',              # 'log' (default) or 'csv'
        log_indicators=True,            # include strategy indicators in data log
        mysql_enabled=True,
        mysql_host='localhost',
        mysql_database='backtrder_web',
        mysql_user='root',
        mysql_password='secret',
    )
"""

import csv
import datetime as dt_module
import io
import json
import os

from ..observer import Observer
from ..trade import Trade
from ..utils.date import num2date


class TradeLogger(Observer):
    """Observer that logs orders, trades, positions, and bar data.

    Records comprehensive information during backtesting in real-time:

    - **order**: Order events (ref, type, status, size, price, etc.)
    - **trade**: Trade events (ref, status, size, price, pnl, etc.)
    - **position**: Position snapshot per bar (size, price)
    - **data**: Bar data per bar (datetime, OHLCV, open interest,
      extra data lines, and optionally strategy indicators)

    Logs are written to files incrementally on every bar (append mode).
    A ``current_position.json`` is maintained with the latest positions.

    Params:
      - ``log_orders`` (default: ``True``): Log order events.
      - ``log_trades`` (default: ``True``): Log trade events.
      - ``log_positions`` (default: ``True``): Log position snapshots.
      - ``log_data`` (default: ``True``): Log bar data.
      - ``extra_fields`` (default: ``None``): Extra data-feed line names
        to log.  ``None`` = auto-detect all non-standard lines.
      - ``log_indicators`` (default: ``False``): Include strategy
        indicators in the data log.
      - ``indicator_names`` (default: ``None``): Specific indicator
        *fullname* list to log.  ``None`` = all indicators.
      - ``log_dir`` (default: ``"logs"``): Root directory for files.
      - ``log_file_enabled`` (default: ``True``): Write files to disk.
      - ``file_format`` (default: ``"log"``): ``"log"`` for
        tab-separated values or ``"csv"`` for standard CSV.
      - ``mysql_enabled`` (default: ``False``): Write to MySQL.
      - ``mysql_host`` (default: ``"localhost"``): MySQL host.
      - ``mysql_port`` (default: ``3306``): MySQL port.
      - ``mysql_user`` (default: ``"root"``): MySQL user.
      - ``mysql_password`` (default: ``""``): MySQL password.
      - ``mysql_database`` (default: ``"backtrder_web"``): MySQL database.
      - ``mysql_table_prefix`` (default: ``"bt"``): Table name prefix.
    """

    _stclock = True

    lines = ("dummy",)

    params = (
        ("log_orders", True),
        ("log_trades", True),
        ("log_positions", True),
        ("log_data", True),
        ("extra_fields", None),
        ("log_indicators", False),
        ("indicator_names", None),
        # File output
        ("log_dir", "logs"),
        ("log_file_enabled", True),
        ("file_format", "log"),
        # MySQL output
        ("mysql_enabled", False),
        ("mysql_host", "localhost"),
        ("mysql_port", 3306),
        ("mysql_user", "root"),
        ("mysql_password", ""),
        ("mysql_database", "backtrder_web"),
        ("mysql_table_prefix", "bt"),
    )

    plotinfo = dict(plot=False, subplot=False)

    def __init__(self):
        """Initialize TradeLogger with empty log lists."""
        self.order_log = []
        self.trade_log = []
        self.position_log = []
        self.data_log = []
        self._run_id = None
        self._run_datetime = None
        self._strategy_name = None
        self._strategy_params = None
        # file handles for real-time writing
        self._file_handles = {}
        self._file_headers_written = {}
        self._log_dir = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def _owner_datas(self):
        """Strategy data feeds (observers have empty self.datas)."""
        if hasattr(self, "_owner") and self._owner is not None:
            return getattr(self._owner, "datas", [])
        return []

    def _init_run_info(self):
        """Lazily capture strategy name / params and build run_id."""
        if self._run_id is not None:
            return
        self._run_datetime = dt_module.datetime.now()
        if hasattr(self, "_owner") and self._owner is not None:
            self._strategy_name = type(self._owner).__name__
            try:
                params_dict = {}
                if hasattr(self._owner, "p") and hasattr(self._owner.p, "_getkwargs"):
                    params_dict = dict(self._owner.p._getkwargs())
                self._strategy_params = json.dumps(params_dict, default=str, ensure_ascii=False)
            except Exception:
                self._strategy_params = "{}"
        else:
            self._strategy_name = "Unknown"
            self._strategy_params = "{}"
        ts = self._run_datetime.strftime("%Y%m%d_%H%M%S")
        self._run_id = f"{self._strategy_name}_{ts}"
        # prepare output directory
        if self.p.log_file_enabled and self.p.log_dir:
            self._log_dir = os.path.join(self.p.log_dir, self._run_id)
            os.makedirs(self._log_dir, exist_ok=True)
            self._write_run_info()

    @staticmethod
    def _dt_to_str(dt):
        """Convert datetime to ``%Y-%m-%d %H:%M:%S`` string or None."""
        if dt is None:
            return None
        if isinstance(dt, dt_module.datetime):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return str(dt)

    @staticmethod
    def _format_value(v):
        """Format a value for file output."""
        if v is None:
            return ""
        if isinstance(v, dt_module.datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(v, bool):
            return str(int(v))
        return str(v)

    @property
    def _separator(self):
        """Field separator: tab for .log, comma for .csv."""
        return "\t" if self.p.file_format == "log" else ","

    @property
    def _file_ext(self):
        """File extension based on file_format."""
        return "log" if self.p.file_format == "log" else "csv"

    def _get_indicators(self):
        """Get strategy indicators and their current values.

        Returns:
            dict: {indicator_fullname: value} for all (or selected) indicators.
        """
        result = {}
        if not hasattr(self, "_owner") or self._owner is None:
            return result
        try:
            indicators = self._owner.getindicators()
        except Exception:
            return result

        allowed = self.p.indicator_names
        for ind in indicators:
            try:
                fullname = getattr(ind, "_name", "") or type(ind).__name__
                aliases = ind.lines.getlinealiases() if hasattr(ind.lines, "getlinealiases") else ()
                for alias in aliases:
                    col_name = f"{fullname}.{alias}"
                    if allowed is not None and col_name not in allowed:
                        continue
                    line = getattr(ind.lines, alias, None)
                    if line is not None and len(line) > 0:
                        try:
                            val = line[0]
                            result[col_name] = val
                        except (IndexError, Exception):
                            result[col_name] = None
            except Exception:
                continue
        return result

    # ------------------------------------------------------------------
    # file I/O helpers (real-time append)
    # ------------------------------------------------------------------

    def _get_file(self, name):
        """Get or create an append-mode file handle for *name*."""
        if name not in self._file_handles:
            if self._log_dir is None:
                return None
            filepath = os.path.join(self._log_dir, f"{name}.{self._file_ext}")
            fh = open(filepath, "a", encoding="utf-8", newline="")
            self._file_handles[name] = fh
            self._file_headers_written[name] = False
        return self._file_handles[name]

    def _append_records(self, name, records):
        """Append *records* (list of dicts) to the named file.

        Writes header on the first call, then appends data rows.
        For .log format, values are tab-separated.
        For .csv format, standard CSV quoting is used.
        """
        if not records or not self.p.log_file_enabled:
            return
        fh = self._get_file(name)
        if fh is None:
            return

        sep = self._separator
        is_csv = self.p.file_format == "csv"

        for record in records:
            keys = list(record.keys())
            # write header if needed
            if not self._file_headers_written[name]:
                if is_csv:
                    writer = csv.writer(fh)
                    writer.writerow(keys)
                else:
                    fh.write(sep.join(keys) + "\n")
                self._file_headers_written[name] = True

            values = [self._format_value(record[k]) for k in keys]
            if is_csv:
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(values)
                fh.write(buf.getvalue())
            else:
                fh.write(sep.join(values) + "\n")

        fh.flush()

    def _write_run_info(self):
        """Write run_info.json once at initialization."""
        if self._log_dir is None:
            return
        run_info = dict(
            run_id=self._run_id,
            strategy_name=self._strategy_name,
            strategy_params=self._strategy_params,
            run_datetime=str(self._run_datetime),
        )
        path = os.path.join(self._log_dir, "run_info.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(run_info, f, indent=2, ensure_ascii=False, default=str)

    def _write_current_position(self, positions):
        """Overwrite current_position.json with latest positions for all data feeds."""
        if self._log_dir is None or not self.p.log_file_enabled:
            return
        path = os.path.join(self._log_dir, "current_position.json")
        serializable = []
        for p in positions:
            row = {}
            for k, v in p.items():
                row[k] = self._format_value(v) if isinstance(v, dt_module.datetime) else v
            serializable.append(row)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)

    def _close_files(self):
        """Close all open file handles."""
        for fh in self._file_handles.values():
            try:
                fh.close()
            except Exception:
                pass
        self._file_handles.clear()

    # ------------------------------------------------------------------
    # per-bar callbacks
    # ------------------------------------------------------------------

    def next(self):
        """Record order, trade, position, and bar data for the current bar."""
        self._init_run_info()

        if self.p.log_orders:
            self._log_orders()
        if self.p.log_trades:
            self._log_trades()
        if self.p.log_positions:
            self._log_positions()
        if self.p.log_data:
            self._log_data()

    def stop(self):
        """Close file handles and flush logs to MySQL."""
        self._init_run_info()
        self._close_files()
        self._save_to_mysql()

    # ------------------------------------------------------------------
    # internal logging (per bar)
    # ------------------------------------------------------------------

    def _log_orders(self):
        """Log pending order events for the current bar."""
        entries = []
        now_str = dt_module.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        for order in self._owner._orderspending:
            entry = dict(
                log_time=now_str,
                ref=order.ref,
                ordtype=order.OrdTypes[order.ordtype] if order.ordtype is not None else "Unknown",
                status=order.Status[order.status],
                size=order.size,
                price=order.created.price if order.created else None,
                exectype=order.ExecTypes[order.exectype] if order.exectype is not None else None,
                executed_price=(
                    order.executed.price if order.executed and order.executed.size else None
                ),
                executed_size=order.executed.size if order.executed else None,
                commission=order.executed.comm if order.executed else None,
                dt=num2date(order.data.datetime[0]) if len(order.data) else None,
                data_name=getattr(order.data, "_name", ""),
            )
            self.order_log.append(entry)
            entries.append(entry)
        self._append_records("order", entries)

    def _log_trades(self):
        """Log pending trade events for the current bar."""
        entries = []
        now_str = dt_module.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        for trade in self._owner._tradespending:
            entry = dict(
                log_time=now_str,
                ref=trade.ref,
                status=Trade.status_names[trade.status],
                size=trade.size,
                price=trade.price,
                value=trade.value,
                commission=trade.commission,
                pnl=trade.pnl,
                pnlcomm=trade.pnlcomm,
                isopen=trade.isopen,
                isclosed=trade.isclosed,
                justopened=trade.justopened,
                baropen=trade.baropen,
                barclose=trade.barclose,
                barlen=trade.barlen,
                dtopen=num2date(trade.dtopen) if trade.dtopen else None,
                dtclose=num2date(trade.dtclose) if trade.dtclose else None,
                data_name=getattr(trade.data, "_name", ""),
                tradeid=trade.tradeid,
                long=trade.long,
            )
            self.trade_log.append(entry)
            entries.append(entry)
        self._append_records("trade", entries)

    def _log_positions(self):
        """Log position snapshot for each data feed in the current bar."""
        entries = []
        now_str = dt_module.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        for data in self._owner_datas:
            if not len(data):
                continue
            position = self._owner.getposition(data)
            entry = dict(
                log_time=now_str,
                dt=num2date(data.datetime[0]),
                data_name=getattr(data, "_name", ""),
                size=position.size,
                price=position.price,
            )
            self.position_log.append(entry)
            entries.append(entry)
        self._append_records("position", entries)
        # update current_position.json
        self._write_current_position(entries)

    def _log_data(self):
        """Log bar data (OHLCV + open interest + extra fields + indicators)."""
        entries = []
        now_str = dt_module.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        # get indicator values once (shared across all data feeds)
        indicator_values = {}
        if self.p.log_indicators:
            indicator_values = self._get_indicators()

        for data in self._owner_datas:
            if not len(data):
                continue

            entry = dict(
                log_time=now_str,
                dt=num2date(data.datetime[0]),
                data_name=getattr(data, "_name", ""),
                open=data.open[0],
                high=data.high[0],
                low=data.low[0],
                close=data.close[0],
                volume=data.volume[0],
                openinterest=data.openinterest[0],
            )

            standard_lines = {
                "close",
                "low",
                "high",
                "open",
                "volume",
                "openinterest",
                "datetime",
            }

            extra_fields = self.p.extra_fields
            all_aliases = data.getlinealiases()

            if extra_fields is not None:
                for field in extra_fields:
                    if hasattr(data.lines, field):
                        line = getattr(data.lines, field)
                        try:
                            entry[field] = line[0]
                        except (IndexError, Exception):
                            entry[field] = None
            else:
                for alias in all_aliases:
                    if alias not in standard_lines:
                        if hasattr(data.lines, alias):
                            line = getattr(data.lines, alias)
                            try:
                                entry[alias] = line[0]
                            except (IndexError, Exception):
                                entry[alias] = None

            # append indicator values
            if indicator_values:
                entry.update(indicator_values)

            self.data_log.append(entry)
            entries.append(entry)
        self._append_records("data", entries)

    # ------------------------------------------------------------------
    # MySQL persistence
    # ------------------------------------------------------------------

    def _save_to_mysql(self):
        """Write all logs to MySQL tables."""
        if not self.p.mysql_enabled:
            return
        if self._run_id is None:
            return

        try:
            import pymysql
        except ImportError:
            import warnings

            warnings.warn(
                "pymysql is not installed – MySQL logging disabled. "
                "Install with:  pip install pymysql"
            )
            return

        conn = pymysql.connect(
            host=self.p.mysql_host,
            port=self.p.mysql_port,
            user=self.p.mysql_user,
            password=self.p.mysql_password,
            database=self.p.mysql_database,
            charset="utf8mb4",
        )
        try:
            self._ensure_mysql_tables(conn)
            self._insert_mysql_logs(conn)
            conn.commit()
        finally:
            conn.close()

    def _ensure_mysql_tables(self, conn):
        """``CREATE TABLE IF NOT EXISTS`` for order, trade, position tables.

        Table design follows best practices:
        - ``run_id`` uniquely identifies each backtest run
        - ``strategy_name`` + ``strategy_params`` distinguish same strategy
          with different parameters
        - ``run_datetime`` distinguishes runs at different times
        - ``log_time`` records the precise wall-clock time the record was
          written (microsecond precision)
        - ``created_at`` auto-set by MySQL on insert for audit trail
        - Composite indexes on (strategy_name, run_id) for efficient queries

        Data logs are NOT stored in MySQL (columns vary per data feed).
        """
        pfx = self.p.mysql_table_prefix
        cursor = conn.cursor()

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS `{pfx}_order` (
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
            CREATE TABLE IF NOT EXISTS `{pfx}_trade` (
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
            CREATE TABLE IF NOT EXISTS `{pfx}_position` (
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

        cursor.close()

    def _insert_mysql_logs(self, conn):
        """Batch-insert order, trade, position logs into MySQL.

        Data logs are NOT inserted (columns vary per data feed).
        """
        pfx = self.p.mysql_table_prefix
        cursor = conn.cursor()
        run_dt = self._dt_to_str(self._run_datetime)

        # ---- order_log ----
        if self.order_log:
            sql = (
                f"INSERT INTO `{pfx}_order` "
                "(`log_time`,`run_id`,`strategy_name`,`strategy_params`,`run_datetime`,"
                "`ref`,`ordtype`,`status`,`size`,`price`,`exectype`,"
                "`executed_price`,`executed_size`,`commission`,`dt`,`data_name`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            rows = [
                (
                    e.get("log_time"),
                    self._run_id,
                    self._strategy_name,
                    self._strategy_params,
                    run_dt,
                    e.get("ref"),
                    e.get("ordtype"),
                    e.get("status"),
                    e.get("size"),
                    e.get("price"),
                    e.get("exectype"),
                    e.get("executed_price"),
                    e.get("executed_size"),
                    e.get("commission"),
                    self._dt_to_str(e.get("dt")),
                    e.get("data_name"),
                )
                for e in self.order_log
            ]
            cursor.executemany(sql, rows)

        # ---- trade_log ----
        if self.trade_log:
            sql = (
                f"INSERT INTO `{pfx}_trade` "
                "(`log_time`,`run_id`,`strategy_name`,`strategy_params`,`run_datetime`,"
                "`ref`,`status`,`size`,`price`,`value`,`commission`,"
                "`pnl`,`pnlcomm`,`isopen`,`isclosed`,`justopened`,"
                "`baropen`,`barclose`,`barlen`,`dtopen`,`dtclose`,"
                "`data_name`,`tradeid`,`is_long`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            rows = [
                (
                    e.get("log_time"),
                    self._run_id,
                    self._strategy_name,
                    self._strategy_params,
                    run_dt,
                    e.get("ref"),
                    e.get("status"),
                    e.get("size"),
                    e.get("price"),
                    e.get("value"),
                    e.get("commission"),
                    e.get("pnl"),
                    e.get("pnlcomm"),
                    int(e.get("isopen", False)),
                    int(e.get("isclosed", False)),
                    int(e.get("justopened", False)),
                    e.get("baropen"),
                    e.get("barclose"),
                    e.get("barlen"),
                    self._dt_to_str(e.get("dtopen")),
                    self._dt_to_str(e.get("dtclose")),
                    e.get("data_name"),
                    e.get("tradeid"),
                    int(e.get("long", False)),
                )
                for e in self.trade_log
            ]
            cursor.executemany(sql, rows)

        # ---- position_log ----
        if self.position_log:
            sql = (
                f"INSERT INTO `{pfx}_position` "
                "(`log_time`,`run_id`,`strategy_name`,`strategy_params`,`run_datetime`,"
                "`dt`,`data_name`,`size`,`price`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            rows = [
                (
                    e.get("log_time"),
                    self._run_id,
                    self._strategy_name,
                    self._strategy_params,
                    run_dt,
                    self._dt_to_str(e.get("dt")),
                    e.get("data_name"),
                    e.get("size"),
                    e.get("price"),
                )
                for e in self.position_log
            ]
            cursor.executemany(sql, rows)

        cursor.close()

    # ------------------------------------------------------------------
    # public getters
    # ------------------------------------------------------------------

    def get_order_log(self):
        """Return the collected order log."""
        return self.order_log

    def get_trade_log(self):
        """Return the collected trade log."""
        return self.trade_log

    def get_position_log(self):
        """Return the collected position log."""
        return self.position_log

    def get_data_log(self):
        """Return the collected data (bar) log."""
        return self.data_log

    def get_all_logs(self):
        """Return all logs as a dictionary."""
        return dict(
            orders=self.order_log,
            trades=self.trade_log,
            positions=self.position_log,
            data=self.data_log,
        )
