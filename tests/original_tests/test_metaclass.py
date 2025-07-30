#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import testcommon


class RunFrompackages(testcommon.SampleParamsHolder):
    """
    This class is used for testing that inheriting from base class that
    uses `frompackages` import mechanism, don't brake the functionality
    of the base class.
    """

    def __init__(self):
        super(RunFrompackages, self).__init__()
        # Prepare the lags array


def test_run(main=False):
    """
    Instantiate the TestFrompackages and see that no exception is raised
    Bug Discussion:
    https://community.backtrader.com/topic/2661/frompackages-directive-functionality-seems-to-be-broken-when-using-inheritance
    """
    test = RunFrompackages()


if __name__ == '__main__':
    test_run(main=True)
