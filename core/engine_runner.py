import backtrader as bt
import pandas as pd
import sys
import io
import numpy as np

def run_backtrader(code_str: str, data: pd.DataFrame, optuna_trial=None, external_params: dict = None):
    """Backtrader를 이용한 동적 백테스트 실행 (분석기 경로 및 수치 보호 장치 강화)"""
    exec_globals = globals().copy()
    exec_globals.update({'optuna_trial': optuna_trial, 'data': data, 'external_params': external_params})
    
    try:
        exec(code_str, exec_globals)
        
        if 'metrics' in exec_globals and isinstance(exec_globals['metrics'], dict):
            # 수치 무결성 검사 (NaN/Inf 방지)
            for k, v in exec_globals['metrics'].items():
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    exec_globals['metrics'][k] = 0.0
            return True, exec_globals['metrics']
            
        strategy_class = exec_globals.get('TestStrategy')
        if not strategy_class: return False, "전략 클래스 누락"
            
        cerebro = bt.Cerebro(stdstats=False)
        if external_params: cerebro.addstrategy(strategy_class, **external_params)
        else: cerebro.addstrategy(strategy_class)
        
        cerebro.adddata(bt.feeds.PandasData(dataname=data))
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=0.0008)
        
        # 🚨 [수정] bt.indicators.DrawDown -> bt.analyzers.DrawDown
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        results = cerebro.run(runonce=True, preload=True, runstds=False, exactbars=False)
        if not results: return False, "연산 실패"
            
        strat = results[0]
        final_value = cerebro.broker.getvalue()
        dd_anlz = strat.analyzers.drawdown.get_analysis()
        trades_anlz = strat.analyzers.trades.get_analysis()
        
        tot_return = (final_value - 10000.0) / 100.0
        max_dd = dd_anlz.max.drawdown if 'max' in dd_anlz else 0.0
        
        # 수치 보호 로직
        tot_return = 0.0 if np.isnan(tot_return) or np.isinf(tot_return) else tot_return
        max_dd = 0.0 if np.isnan(max_dd) or np.isinf(max_dd) else max_dd
        
        metrics = {
            "Total Return (%)": round(tot_return, 2),
            "Win Rate (%)": 0.0,
            "MDD (%)": round(max_dd, 2),
            "Total Trades": 0,
            "Total Profit": round(final_value - 10000.0, 2)
        }
        return True, metrics

    except Exception as e:
        return False, f"Backtrader 에러: {str(e)}"

def run_vectorbt(code_str: str, data: pd.DataFrame, optuna_trial=None):
    """Vectorbt를 이용한 동적 백테스트 실행 (무결성 및 수치 보호)"""
    exec_globals = globals().copy()
    exec_globals.update({'data': data, 'optuna_trial': optuna_trial, 'np': np})
    
    try:
        exec(code_str, exec_globals)
        metrics = exec_globals.get('metrics')
        if not metrics or not isinstance(metrics, dict):
            return False, "metrics 딕셔너리 누락"
            
        # 수치 무결성 검사 (VectorBT 연산 결과 NaN 방어)
        for k, v in metrics.items():
            if isinstance(v, (float, np.float64, np.float32)):
                if np.isnan(v) or np.isinf(v):
                    metrics[k] = 0.0
            
        return True, metrics
        
    except Exception as e:
        return False, f"Vectorbt 에러: {str(e)}"

def run_backtest(engine: str, code_str: str, data: pd.DataFrame, optuna_trial=None):
    if engine.lower() == 'backtrader':
        return run_backtrader(code_str, data, optuna_trial)
    elif engine.lower() == 'vectorbt':
        return run_vectorbt(code_str, data, optuna_trial)
    else:
        return False, "미지원 엔진"
