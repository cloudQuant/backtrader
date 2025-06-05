import sys
import time

print("Starting test...", flush=True)

# Set timer
start_time = time.time()

try:
    print("1. Importing backtrader...", flush=True)
    import backtrader as bt
    print(f"2. Import done in {time.time() - start_time:.2f}s", flush=True)
    
    print("3. Creating basic strategy...", flush=True)
    class TestStrategy(bt.Strategy):
        def __init__(self):
            print("Strategy init called", flush=True)
            
    print("4. Creating Cerebro...", flush=True)
    cerebro = bt.Cerebro()
    
    print("5. Adding strategy...", flush=True)
    cerebro.addstrategy(TestStrategy)
    
    print("6. Creating CSV data...", flush=True)
    # Use real CSV data from backtrader samples if available
    import os
    sample_data_path = 'samples/orcl-1995-2014.txt'
    if os.path.exists(sample_data_path):
        print("Using sample data file", flush=True)
        data = bt.feeds.YahooFinanceCSVData(dataname=sample_data_path)
        cerebro.adddata(data)
        
        print("7. Starting Cerebro run...", flush=True)
        result = cerebro.run()
        print("8. Cerebro run completed!", flush=True)
    else:
        print("Sample data not found, skipping run", flush=True)
        
except Exception as e:
    print(f"ERROR at {time.time() - start_time:.2f}s: {e}", flush=True)
    import traceback
    traceback.print_exc()
    
print(f"Test completed in {time.time() - start_time:.2f}s", flush=True) 