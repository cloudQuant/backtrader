#!/usr/bin/env python

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from backtrader.brokers.bbroker import BackBroker as BackBroker, BrokerBack as BrokerBack

try:
    from backtrader.brokers.ibbroker import IBBroker as IBBroker
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from backtrader.brokers.vcbroker import VCBroker as VCBroker
except ImportError:
    pass  # The user may not have something installed

try:
    from backtrader.brokers.oandabroker import OandaBroker as OandaBroker
except ImportError:
    pass  # The user may not have something installed
