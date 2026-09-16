"""Cerebro vectorized engine mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: ``_runonce`` (modern) and
``_runonce_old`` (oldsync).
"""

from ..feed import AbstractDataBase


class RunOnceMixin:
    """Vectorized engine half of Cerebro (see module docstring)."""

    # Old runonce method, similar to runonce
    def _runonce_old(self, runstrats):
        """
        Actual implementation of run in vector mode.
        Strategies are still invoked on a pseudo-event mode in which `next`
        is called for each data arrival
        """

        for strat in runstrats:
            strat._once()

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        data0 = self.datas[0]
        datas = self.datas[1:]
        for i in range(data0.buflen()):
            self._storenotify()
            if self._event_stop:  # stop if requested
                return
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            data0.advance()
            for data in datas:
                data.advance(datamaster=data0)

            self._brokernotify()
            if self._event_stop:  # stop if requested
                return

            for strat in runstrats:
                # data0.datetime[0] for compat. w/ new strategy's oncepost
                strat._oncepost(data0.datetime[0])
                if self._event_stop:  # stop if requested
                    return

                self._next_writers(runstrats)

        self._datanotify()
        if self._event_stop:  # stop if requested
            return
        self._storenotify()
        if self._event_stop:  # stop if requested
            return

    # runonce
    def _runonce(self, runstrats):
        """
        Actual implementation of run in vector mode.

        Strategies are still invoked on a pseudo-event mode in which `next`
        is called for each data arrival
        """
        # Iterate strategies, call _once and reset
        for strat in runstrats:
            strat._once()
            strat.reset()  # strat called next by next - reset lines

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        # Sort data from small period to large period
        datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
        data0 = datas[0]
        single_data = len(datas) == 1
        single_default_datanotify = (
            single_data and type(data0).get_notifications is AbstractDataBase.get_notifications
        )
        cheat_on_open = self.p.cheat_on_open
        has_timers = bool(self._timers)
        has_timerscheat = bool(self._timerscheat)
        has_stores = bool(self.stores)
        has_runwriters = bool(self.runwriters)

        while True:
            if has_stores:
                self._storenotify()
                if self._event_stop:  # stop if requested
                    return
            if not single_default_datanotify or data0.notifs:
                self._datanotify()
            if self._event_stop:  # stop if requested
                return

            # Check the next incoming date in the datas
            # For each data call advance_peek(), get minimum time as the first one
            dts = [d.advance_peek() for d in datas]
            dt0 = min(dts)
            if dt0 == float("inf"):
                break  # no data delivers anything

            # Timemaster if needed be
            # dmaster = datas[dts.index(dt0)]  # and timemaster
            # For each data time, if time <= minimum time, advance data, otherwise ignore
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datas[i].advance()
                    # self._plotfillers2[i].append(slen)  # mark as fill
                else:
                    # self._plotfillers[i].append(slen)
                    pass
            # Check timer
            if has_timerscheat:
                self._check_timers(runstrats, dt0, cheat=True)
            # If cheat_on_open, call _oncepost_open() for each strategy
            if cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    # If stop was called, stop
                    if self._event_stop:  # stop if requested
                        return
            # Call _brokernotify()
            self._brokernotify()
            # If stop was called, stop
            if self._event_stop:  # stop if requested
                return
            # Check timer
            if has_timers:
                self._check_timers(runstrats, dt0, cheat=False)

            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:  # stop if requested
                    return
                if has_runwriters:
                    self._next_writers(runstrats)
