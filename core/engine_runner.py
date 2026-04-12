import backtrader as bt
import pandas as pd
import sys
import io

def run_backtrader(code_str: str, data: pd.DataFrame, optuna_trial=None, external_params: dict = None):
    """Backtrader를 이용한 동적 백테스트 실행 (Hyper-Speed 최적화 버전)"""
    # 전역과 지역을 통합하여 변수 접근 유실 방지
    exec_globals = globals().copy()
    exec_globals.update({'optuna_trial': optuna_trial, 'data': data, 'external_params': external_params})
    
    try:
        # 1. 컴파일 오버헤드 최소화를 위한 exec 환경 설정
        exec(code_str, exec_globals)
        
        # 사용자가 직접 metrics를 반환한 경우 (새 템플릿 방식)
        if 'metrics' in exec_globals and isinstance(exec_globals['metrics'], dict):
            return True, exec_globals['metrics']
            
        strategy_class = exec_globals.get('TestStrategy')
        if not strategy_class:
            return False, "전략 코드에 'TestStrategy' 이름의 클래스가 정의되지 않았습니다."
            
        cerebro = bt.Cerebro(stdstats=False) # 표준 통계 시각화 비활성으로 가속
        
        # 파라미터 주입 최적화
        if external_params:
            cerebro.addstrategy(strategy_class, **external_params)
        else:
            cerebro.addstrategy(strategy_class)
        
        data_feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(data_feed)
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=0.0008)
        
        cerebro.addanalyzer(bt.indicators.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        results = cerebro.run(runonce=True, preload=True, runstds=False, exactbars=False)
        if not results: return False, "연산 실패"
            
        strat = results[0]
        final_value = cerebro.broker.getvalue()
        dd_anlz = strat.analyzers.drawdown.get_analysis()
        trades_anlz = strat.analyzers.trades.get_analysis()
        
        tot_return = (final_value - 10000.0) / 100.0
        max_dd = dd_anlz.max.drawdown if 'max' in dd_anlz else 0.0
        total_trades = trades_anlz.total.closed if hasattr(trades_anlz, 'total') and hasattr(trades_anlz.total, 'closed') else 0
        
        win_rate = 0.0
        if total_trades > 0 and hasattr(trades_anlz, 'won'):
            win_rate = (trades_anlz.won.total / total_trades) * 100
            
        metrics = {
            "Total Return (%)": round(tot_return, 2),
            "Win Rate (%)": round(win_rate, 2),
            "Max Drawdown (%)": round(max_dd, 2),
            "Total Trades": total_trades,
            "Total Profit": round(final_value - 10000.0, 2)
        }
        return True, metrics

    except Exception as e:
        return False, f"Backtrader 엔진 자체 에러: {str(e)}"

def run_vectorbt(code_str: str, data: pd.DataFrame, optuna_trial=None):
    """Vectorbt를 이용한 동적 백테스트 실행 (통합 네임스페이스 안정화 버전)"""
    # 전역과 지역을 통합하여 변수 접근 유실 방지 (optuna_trial 실시간 바인딩 보장)
    exec_globals = globals().copy()
    exec_globals.update({'data': data, 'optuna_trial': optuna_trial})
    
    try:
        # 통합 네임스페이스에서 실행하여 'optuna_trial' 변수 유실 방지
        exec(code_str, exec_globals)
        
        # 전략 코드 내부에서 생성된 metrics 딕셔너리 추출
        metrics = exec_globals.get('metrics')
        if not metrics or not isinstance(metrics, dict):
            return False, "스크립트가 올바른 'metrics' 딕셔너리를 생성하지 않았습니다. 템플릿의 끝부분을 확인해주세요."
            
        return True, metrics
        
    except Exception as e:
        return False, f"Vectorbt 엔진 파이프라인 에러: {str(e)}"

def run_backtest(engine: str, code_str: str, data: pd.DataFrame, optuna_trial=None):
    if engine.lower() == 'backtrader':
        return run_backtrader(code_str, data, optuna_trial)
    elif engine.lower() == 'vectorbt':
        return run_vectorbt(code_str, data, optuna_trial)
    else:
        return False, "지원하지 않는 엔진입니다."
