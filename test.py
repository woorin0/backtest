import backtrader as bt
import pandas as pd
import datetime
import math

class TestStrategy(bt.Strategy):
    params = (
        ('ma1_length', 20),
    )
    def __init__(self):
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        
        # Test line that might be failing
        vol_src = (self.datahigh - self.datalow) / bt.And(self.dataclose, bt.If(self.dataclose > 0, self.dataclose, 0.000001))
        self.ma1 = bt.indicators.SMA(vol_src, period=self.p.ma1_length)

data = pd.DataFrame({
    'Open': [100, 101, 102],
    'High': [105, 106, 107],
    'Low': [95, 96, 97],
    'Close': [101, 102, 103],
    'Volume': [1000, 1500, 1200]
}, index=pd.date_range('2023-01-01', periods=3))

cerebro = bt.Cerebro()
data_feed = bt.feeds.PandasData(dataname=data)
cerebro.adddata(data_feed)
cerebro.addstrategy(TestStrategy)
try:
    cerebro.run()
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
