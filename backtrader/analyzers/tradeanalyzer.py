#!/usr/bin/env python
from ..analyzer import Analyzer
from ..utils import AutoDict, AutoOrderedDict
from ..utils.py3 import MAXINT


# Analyze trades
class TradeAnalyzer(Analyzer):
    """
    Provides statistics on closed trades (keeps also the count of open ones)

      - Total Open/Closed Trades

      - Streak Won/Lost Current/Longest

      - ProfitAndLoss Total/Average

      - Won/Lost Count/ Total PNL/ Average PNL / Max PNL

      - Long/Short Count/ Total PNL / Average PNL / Max PNL

          - Won/Lost Count/ Total PNL/ Average PNL / Max PNL

      - Length (bars in the market)

        - Total/Average/Max/Min

        - Won/Lost Total/Average/Max/Min

        - Long/Short Total/Average/Max/Min

          - Won/Lost Total/Average/Max/Min

    Note:

      The analyzer uses an autodict for the fields, which means that if no
      trades are executed, no statistics will be generated.

      In that case, there will be a single field/subfield in the dictionary
      returned by ``get_analysis``, namely:

        - Dictname['total']['total'] which will have a value of 0 (the field is
          also reachable with dot notation dictname.total.total
    """

    rets = None

    # Create analysis
    def create_analysis(self):
        self.rets = AutoOrderedDict()
        self.rets.total.total = 0

    # Stop
    def stop(self):
        super().stop()
        self.rets._close()

    # Trade notification
    def notify_trade(self, trade):
        # If trade just opened
        if trade.justopened:
            # Trade just opened
            self.rets.total.total += 1
            self.rets.total.open += 1
        # If trade is closed
        elif trade.status == trade.Closed:
            trades = self.rets

            res = AutoDict()
            # Trade just closed
            # Profit
            res.won = int(trade.pnlcomm >= 0.0)
            # Loss
            res.lost = int(not res.won)
            # Long position
            res.tlong = trade.long
            # Short position
            res.tshort = not trade.long
            # Opened trade
            trades.total.open -= 1
            # Closed trade
            trades.total.closed += 1

            # Streak
            # Calculate consecutive win and loss counts
            for wlname in ["won", "lost"]:
                # Current win/loss status
                wl = res[wlname]
                # Current consecutive win or loss count
                trades.streak[wlname].current *= wl
                trades.streak[wlname].current += wl
                # Get maximum consecutive win or loss count
                ls = trades.streak[wlname].longest or 0
                # Recalculate
                trades.streak[wlname].longest = max(ls, trades.streak[wlname].current)
            # Trade profit/loss
            trpnl = trades.pnl
            # Total trade profit/loss
            trpnl.gross.total += trade.pnl
            # Average profit/loss
            trpnl.gross.average = trades.pnl.gross.total / trades.total.closed
            # Net trade profit/loss
            trpnl.net.total += trade.pnlcomm
            # Average net profit/loss
            trpnl.net.average = trades.pnl.net.total / trades.total.closed

            # Won/Lost statistics
            # Win/loss statistics
            for wlname in ["won", "lost"]:
                # Current win/loss
                wl = res[wlname]
                # Historical win/loss
                trwl = trades[wlname]
                # Win/loss count
                trwl.total += wl  # won.total / lost.total
                # Total and average profit/loss
                trwlpnl = trwl.pnl
                pnlcomm = trade.pnlcomm * wl

                trwlpnl.total += pnlcomm
                trwlpnl.average = trwlpnl.total / (trwl.total or 1.0)
                # Maximum profit or minimum loss (largest losing trade)
                wm = trwlpnl.max or 0.0
                func = max if wlname == "won" else min
                trwlpnl.max = func(wm, pnlcomm)

            # Long/Short statistics
            # Long/short statistics
            for tname in ["long", "short"]:
                # Long and short
                trls = trades[tname]
                # Current trade's long and short
                ls = res["t" + tname]
                # Calculate long and short counts
                trls.total += ls  # long.total / short.total
                # Calculate total pnl for long and short
                trls.pnl.total += trade.pnlcomm * ls
                # Calculate average profit for long and short
                trls.pnl.average = trls.pnl.total / (trls.total or 1.0)
                # Analyze win/loss status for long and short
                for wlname in ["won", "lost"]:
                    wl = res[wlname]
                    pnlcomm = trade.pnlcomm * wl * ls

                    trls[wlname] += wl * ls  # long.won / short.won

                    trls.pnl[wlname].total += pnlcomm
                    trls.pnl[wlname].average = trls.pnl[wlname].total / (trls[wlname] or 1.0)

                    wm = trls.pnl[wlname].max or 0.0
                    func = max if wlname == "won" else min
                    trls.pnl[wlname].max = func(wm, pnlcomm)

            # Length
            # Number of bars occupied by trade
            trades.len.total += trade.barlen
            # Average number of bars per trade
            trades.len.average = trades.len.total / trades.total.closed
            # Maximum number of bars occupied by trade
            ml = trades.len.max or 0
            trades.len.max = max(ml, trade.barlen)
            # Minimum number of bars occupied by trade
            ml = trades.len.min or MAXINT
            trades.len.min = min(ml, trade.barlen)

            # Length Won/Lost
            # Number of bars for winning/losing trades, similar to above but separated by profit and loss
            for wlname in ["won", "lost"]:
                trwl = trades.len[wlname]
                wl = res[wlname]

                trwl.total += trade.barlen * wl
                trwl.average = trwl.total / (trades[wlname].total or 1.0)

                m = trwl.max or 0
                trwl.max = max(m, trade.barlen * wl)
                if trade.barlen * wl:
                    m = trwl.min or MAXINT
                    trwl.min = min(m, trade.barlen * wl)

            # Length Long/Short
            # Distinguish long and short lengths
            for lsname in ["long", "short"]:
                trls = trades.len[lsname]  # trades.len.long
                ls = res["t" + lsname]  # tlong/tshort

                barlen = trade.barlen * ls

                trls.total += barlen  # trades.len.long.total
                total_ls = trades[lsname].total  # trades.long.total
                trls.average = trls.total / (total_ls or 1.0)

                # max/min
                m = trls.max or 0
                trls.max = max(m, barlen)
                m = trls.min or MAXINT
                trls.min = min(m, barlen or m)
                # Distinguish winning and losing lengths for long and short
                for wlname in ["won", "lost"]:
                    wl = res[wlname]  # won/lost

                    barlen2 = trade.barlen * ls * wl

                    trls_wl = trls[wlname]  # trades.len.long.won
                    trls_wl.total += barlen2  # trades.len.long.won.total

                    trls_wl.average = trls_wl.total / (trades[lsname][wlname] or 1.0)

                    # max/min
                    m = trls_wl.max or 0
                    trls_wl.max = max(m, barlen2)
                    m = trls_wl.min or MAXINT
                    trls_wl.min = min(m, barlen2 or m)
