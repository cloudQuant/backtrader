import array,hashlib,json,math,os,pathlib,platform,sys,time
import pandas as pd, numpy as np, backtrader as bt
import backtrader.indicators.contrib.digital_macd as module
period=int(sys.argv[1]);once=sys.argv[2]=='1';n=8000
values=[100.0+i*0.0001+math.sin(i*0.071)*3.0 for i in range(n)]
raw=array.array('d',values).tobytes();df=pd.DataFrame({'open':values,'high':values,'low':values,'close':values,'volume':[1.]*n,'openinterest':[0.]*n},index=pd.date_range('2024-01-01',periods=n,freq='min'))
class Probe(bt.Strategy):
 def __init__(self):self.ind=bt.indicators.DigitalMacd(self.data,signal_period=period,point=.01)
def once_run(frame):
 c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(bt.feeds.PandasData(dataname=frame));c.addstrategy(Probe);start=time.perf_counter();out=c.run(preload=True)[0];elapsed=time.perf_counter()-start;return elapsed,out
once_run(df.iloc[:400]);elapsed,out=once_run(df)
h=hashlib.sha256();h.update(out.ind.macd.array.tobytes());h.update(out.ind.signal.array.tobytes())
print(json.dumps({'seconds':elapsed,'data_sha256':hashlib.sha256(raw).hexdigest(),'output_sha256':h.hexdigest(),'source_sha256':hashlib.sha256(pathlib.Path(module.__file__).read_bytes()).hexdigest(),'origin':module.__file__,'python':sys.version,'numpy':np.__version__,'pandas':pd.__version__,'platform':platform.platform(),'processor':platform.processor(),'period':period,'once':once,'rows':n}))
