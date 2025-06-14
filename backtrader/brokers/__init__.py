#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from backtrader.brokers.bbroker import BackBroker, BrokerBack

try:
    from backtrader.brokers.ibbroker import IBBroker
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from backtrader.brokers.vcbroker import VCBroker
except ImportError:
    pass  # The user may not have something installed

try:
    from backtrader.brokers.oandabroker import OandaBroker
except ImportError as e:
    pass  # The user may not have something installed
