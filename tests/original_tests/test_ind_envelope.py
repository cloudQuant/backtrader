#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2023 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
    ["4165.049575", "3735.555783", "3643.560667"],
    ["3961.876425", "3553.333550", "3465.826000"],
]

chkmin = 30
chkind = btind.Envelope


class TS2(testcommon.TestStrategy):
    def __init__(self):
        print(f"DEBUG: btind.MovAv.SMA = {btind.MovAv.SMA}")
        print(f"DEBUG: btind.MovAv.SMA.__bases__ = {getattr(btind.MovAv.SMA, '__bases__', 'NO BASES')}")
        print(f"DEBUG: Creating SMA indicator...")
        print(f"DEBUG: self.data = {self.data}")
        print(f"DEBUG: type(self.data) = {type(self.data)}")
        
        try:
            print(f"DEBUG: About to call btind.MovAv.SMA(self.data)")
            ind = btind.MovAv.SMA(self.data)
            print(f"DEBUG: SMA creation returned: {ind}")
            print(f"DEBUG: SMA indicator type: {type(ind)}")
        except Exception as e:
            print(f"ERROR: SMA creation failed: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        print(f"DEBUG: SMA indicator created: {ind}")
        print(f"DEBUG: SMA indicator type: {type(ind)}")
        print(f"DEBUG: SMA indicator MRO: {type(ind).__mro__}")
        print(f"DEBUG: SMA indicator _owner: {getattr(ind, '_owner', 'NO OWNER')}")
        print(f"DEBUG: SMA indicator has __init__: {hasattr(ind, '__init__')}")
        print(f"DEBUG: About to set inddata")
        self.p.inddata = [ind]
        print(f"DEBUG: inddata set to: {self.p.inddata}")
        super(TS2, self).__init__()


def test_run(main=True):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas, TS2, main=main, plot=main, chkind=chkind, chkmin=chkmin, chkvals=chkvals
    )


if __name__ == "__main__":
    test_run(main=True)
