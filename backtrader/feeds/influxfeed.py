#!/usr/bin/env python

import datetime as dt

from ..dataseries import TimeFrame
from ..feed import DataBase
from ..utils import date2num

try:
    from influxdb import InfluxDBClient as idbclient
    from influxdb.exceptions import InfluxDBClientError
except Exception:  # pragma: no cover - optional dependency, handled at runtime
    idbclient = None

    class InfluxDBClientError(Exception):
        pass


# Time period mapping
TIMEFRAMES = dict(
    (
        (TimeFrame.Seconds, "s"),
        (TimeFrame.Minutes, "m"),
        (TimeFrame.Days, "d"),
        (TimeFrame.Weeks, "w"),
        (TimeFrame.Months, "m"),
        (TimeFrame.Years, "y"),
    )
)


# backtrader fetches data from InfluxDB
class InfluxDB(DataBase):
    # Import packages
    frompackages = (
        ("influxdb", [("InfluxDBClient", "idbclient")]),
        ("influxdb.exceptions", "InfluxDBClientError"),
    )
    # Parameters
    params = (
        ("host", "127.0.0.1"),
        ("port", "8086"),
        ("username", None),
        ("password", None),
        ("database", None),
        ("timeframe", TimeFrame.Days),
        ("startdate", None),
        ("high", "high_p"),
        ("low", "low_p"),
        ("open", "open_p"),
        ("close", "close_p"),
        ("volume", "volume"),
        ("ointerest", "oi"),
    )

    # Start
    def __init__(self):
        self.biter = None
        self.ndb = None

    def start(self):
        super().start()
        # Try to connect to database
        try:
            self.ndb = idbclient(
                self.p.host, self.p.port, self.p.username, self.p.password, self.p.database
            )
        except InfluxDBClientError as err:
            print("Failed to establish connection to InfluxDB: %s" % err)
        # Specific time period
        tf = "{multiple}{timeframe}".format(
            multiple=(self.p.compression if self.p.compression else 1),
            timeframe=TIMEFRAMES.get(self.p.timeframe, "d"),
        )
        # Start time
        if not self.p.startdate:
            st = "<= now()"
        else:
            st = ">= '%s'" % self.p.startdate

        # The query could already consider parameters like fromdate and todate
        # to have the database skip them and not the internal code
        # Specific commands needed for database data retrieval
        qstr = (
            'SELECT mean("{open_f}") AS "open", mean("{high_f}") AS "high", '
            'mean("{low_f}") AS "low", mean("{close_f}") AS "close", '
            'mean("{vol_f}") AS "volume", mean("{oi_f}") AS "openinterest" '
            'FROM "{dataname}" '
            "WHERE time {begin} "
            "GROUP BY time({timeframe}) fill(none)"
        ).format(
            open_f=self.p.open,
            high_f=self.p.high,
            low_f=self.p.low,
            close_f=self.p.close,
            vol_f=self.p.volume,
            oi_f=self.p.ointerest,
            timeframe=tf,
            begin=st,
            dataname=self.p.dataname,
        )
        # Get data
        try:
            dbars = list(self.ndb.query(qstr).get_points())
        except InfluxDBClientError as err:
            print("InfluxDB query failed: %s" % err)
        # Iterate data
        self.biter = iter(dbars)

    def _load(self):
        # Try to get next bar data, then add to line
        try:
            bar = next(self.biter)
        except StopIteration:
            return False

        self.l.datetime[0] = date2num(dt.datetime.strptime(bar["time"], "%Y-%m-%dT%H:%M:%SZ"))

        self.l.open[0] = bar["open"]
        self.l.high[0] = bar["high"]
        self.l.low[0] = bar["low"]
        self.l.close[0] = bar["close"]
        self.l.volume[0] = bar["volume"]

        return True
