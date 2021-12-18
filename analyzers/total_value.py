from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from collections import OrderedDict
from backtrader import Analyzer

class TotalValue(Analyzer):
    '''This analyzer will get total value from every next.

    Params:
    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    '''

    params = ( )

    def start(self):
        super(TotalValue, self).start()
        self.rets = OrderedDict()

    def next(self):
        # Calculate the return
        super(TotalValue, self).next()
        self.rets[self.datas[0].datetime.datetime()] = self.strategy.broker.getvalue()
        
    def get_analysis(self):
        return self.rets