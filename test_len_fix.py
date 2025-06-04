#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import testcommon
import backtrader.indicators as btind

# Test the __len__ method fix directly
class TestLenStrategy(testcommon.TestStrategy):
    def nextstart(self):
        print(f'TestLenStrategy.nextstart called:')
        print(f'  Before setting chkmin, len(self): {len(self)}')
        print(f'  Expected chkmin: {self.p.chkmin}')
        print(f'  TEMA _minperiod: {self.ind._minperiod}')
        
        # This is the critical line from TestStrategy
        self.chkmin = len(self)  # This should now return 88, not 1!
        print(f'  After setting chkmin: {self.chkmin}')
        
        # Call super nextstart 
        super(testcommon.TestStrategy, self).nextstart()

# Run TEMA test
chkdatas = 1
chkvals = [['4113.721705', '3862.386854', '3832.691054']]
chkmin = 88
chkind = btind.TEMA

datas = [testcommon.getdata(i) for i in range(chkdatas)]
try:
    testcommon.runtest(
        datas,
        TestLenStrategy,
        main=False,
        plot=False,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
        runonce=False,  # Force only one test run
        preload=False,
        exbar=False,
    )
except Exception as e:
    print('Exception:', e) 