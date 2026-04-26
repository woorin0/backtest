import backtrader as bt
import pandas as pd
import sys
import io
import numpy as np
import hashlib

_bt_namespace_cache = {}

def run_backtrader(code_str: str, data: pd.DataFrame, optuna_trial=None, external_params: dict = None):
    """Backtrader를 이용한 동적 백테스트 실행 (메모리 캐싱 및 수치 보호 장치 강화)"""
    code_hash = hashlib.md5(code_str.encode('utf-8')).hexdigest()
    if code_hash not in _bt_namespace_cache:
        _bt_namespace_cache[code_hash] = globals().copy()
        
    exec_globals = _bt_namespace_cache[code_hash]
    exec_globals['optuna_trial'] = optuna_trial
    exec_globals['data'] = data
    exec_globals['external_params'] = external_params
    
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

_vbt_namespace_cache = {}

def run_vectorbt(code_str: str, data: pd.DataFrame, optuna_trial=None, target_tf: str = "2h"):
    """Vectorbt를 이용한 동적 백테스트 실행 (무결성 및 OOM 방지 네임스페이스 캐싱)"""
    # [설정] VectorBT 글로벌 캐시 비활성화 (메모리 해제를 위함)
    import vectorbt as vbt
    if getattr(vbt.settings, 'caching', None) is not None:
        vbt.settings.caching['enabled'] = False
        
    # [메모리 누수 방지] Numba JIT 컴파일 재활용을 위한 캐싱 처리
    code_hash = hashlib.md5(code_str.encode('utf-8')).hexdigest()
    if code_hash not in _vbt_namespace_cache:
        _vbt_namespace_cache[code_hash] = globals().copy()
        
    exec_globals = _vbt_namespace_cache[code_hash]
    
    # [V9.0] 디버깅 및 데이터 업데이트를 위해 로컬 변수 주입 (target_tf 추가)
    exec_globals['data'] = data
    exec_globals['optuna_trial'] = optuna_trial
    exec_globals['target_tf'] = target_tf
    exec_globals['np'] = np
    exec_globals['pd'] = pd
    
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
            
        # [V15] 메모리 누수 방지를 위한 안전한 참조 해제 (Numba 환경 파괴 방지)
        ret_metrics = metrics.copy()
        
        # 거대 참조 객체들만 명시적으로 None 처리하여 GC가 회수하게 함.
        for safe_key in ['portfolio', 'data', 'stats', 'atr_tp', 'atr_sl']:
            if safe_key in exec_globals:
                exec_globals[safe_key] = None
        
        import gc
        gc.collect()
                
        return True, ret_metrics
        
    except Exception as e:
        # [V13] 상세 에러 리포팅
        err_msg = str(e)
        diag = f"Vectorbt 에러: {err_msg}"
        return False, diag
    finally:
        import gc
        gc.collect()

def run_backtest(engine: str, code_str: str, data: pd.DataFrame, optuna_trial=None, target_tf: str = "2h"):
    if engine.lower() == 'backtrader':
        return run_backtrader(code_str, data, optuna_trial) # Backtrader는 MTF 미지원 시 기존대로
    elif engine.lower() == 'vectorbt':
        return run_vectorbt(code_str, data, optuna_trial, target_tf)
    else:
        return False, "미지원 엔진"
