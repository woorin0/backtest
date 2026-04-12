import numpy as np
import pandas as pd
import vectorbt as vbt
import traceback

def test():
    try:
        # Create dummy data
        dates = pd.date_range("2023-01-01", periods=10)
        c = np.array([100, 110, 105, 95, 120, 130, 125, 140, 150, 145], dtype=np.float64)
        c_series = pd.Series(c, index=dates)

        en = np.zeros(10, dtype=np.bool_)
        ex = np.zeros(10, dtype=np.bool_)
        pr = c.copy()

        # Buy 100% at day 1
        en[1] = True
        pr[1] = 110.01  # Slippage simulated

        # Sell 100% at day 4
        ex[4] = True
        pr[4] = 119.99  # Slippage simulated

        print("Testing with size=1.0, size_type='percent', fees=0.0008")
        pf = vbt.Portfolio.from_signals(
            c_series,
            en, 
            ex, 
            price=pr, 
            size=1.0, 
            size_type='percent', 
            init_cash=1000000.0, 
            fees=0.0008
        )
        print("Final cash:", pf.cash()[-1])
        print("Success without cash NaN!")

    except Exception as e:
        print("Error caught:", e)
        traceback.print_exc()

test()
