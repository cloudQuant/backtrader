"""Local validation consumes the public SDK's native quantity/price rules."""

import backtrader as bt
import pytest

from tests.fixtures.fake_btapi import FakeBtApiClient, make_bar, make_store
