import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        print("TestStrategy.__init__ called")
        # CRITICAL FIX: Only create SMA if we have data
        if hasattr(self, 'datas') and self.datas:
            self.sma = btind.SMA(period=14)
            print("SMA indicator created successfully")
        else:
            print("No data available for SMA")

print("Creating cerebro...")
cerebro = bt.Cerebro()
print("Adding strategy...")
cerebro.addstrategy(TestStrategy)

# Add some fake data for testing
print("Creating test data...")
import datetime
import backtrader.feeds as btfeeds

# Create test data
test_data = []
start_date = datetime.datetime(2020, 1, 1)
for i in range(100):
    date = start_date + datetime.timedelta(days=i)
    # Simple fake OHLCV data
    close = 100 + i * 0.1
    test_data.append([
        date, close-1, close+1, close-0.5, close, 1000, 0
    ])

# Use built-in data feed
data = btfeeds.PandasData(dataname=None)
# Manually set up basic data for testing
class SimpleTestData(bt.feed.DataBase):
    def __init__(self):
        super().__init__()
        self.counter = 0
        
    def _load(self):
        if self.counter >= 50:  # Limited data points to prevent infinite loops
            return False
        
        # Add simple test bar
        self.lines.datetime[0] = bt.date2num(datetime.datetime(2020, 1, 1) + datetime.timedelta(days=self.counter))
        self.lines.open[0] = 100 + self.counter
        self.lines.high[0] = 102 + self.counter
        self.lines.low[0] = 98 + self.counter  
        self.lines.close[0] = 101 + self.counter
        self.lines.volume[0] = 1000
        self.lines.openinterest[0] = 0
        
        self.counter += 1
        return True

print("Adding test data...")
test_data_feed = SimpleTestData()
cerebro.adddata(test_data_feed)

print("Starting cerebro run...")
try:
    cerebro.run()
    print("Cerebro run completed successfully!")
except Exception as e:
    print(f"Error during cerebro.run(): {e}")
    import traceback
    traceback.print_exc() 