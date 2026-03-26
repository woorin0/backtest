import backtrader as bt
import pandas as pd
import sys
import io

def run_backtrader(code_str: str, data: pd.DataFrame):
    """Backtrader를 이용한 동적 백테스트 실행"""
    local_env = {}
    
    # 1. 런타임 코드 실행 (보안 샌드박스 없음 - 개인 로컬 구동용)
    try:
        exec(code_str, globals(), local_env)
        
        strategy_class = local_env.get('TestStrategy')
        if not strategy_class:
            return False, "전략 코드에 'TestStrategy' 이름의 클래스가 정의되지 않았습니다."
            
        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy_class)
        
        # DataFrame 컨버팅
        data_feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(data_feed)
        
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=0.001) # 0.1% 커미션
        
        # 결과 분석을 위한 Analyzer 추가
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        # 스탠다드 아웃풋 리다이렉션 방지 (cerebro.run에 의한 stdout 방지용 등)
        results = cerebro.run()
        if not results:
            return False, "비정상적인 실행 (원인 불명)"
            
        strat = results[0]
        
        # 메트릭 파싱
        final_value = cerebro.broker.getvalue()
        dd_anlz = strat.analyzers.drawdown.get_analysis()
        trades_anlz = strat.analyzers.trades.get_analysis()
        
        tot_return = (final_value - 10000.0) / 10000.0 * 100
        max_dd = dd_anlz.max.drawdown if 'max' in dd_anlz else 0.0
        
        total_trades = trades_anlz.total.closed if hasattr(trades_anlz, 'total') and hasattr(trades_anlz.total, 'closed') else 0
        
        if total_trades > 0 and hasattr(trades_anlz, 'won') and hasattr(trades_anlz.won, 'total'):
            win_rate = (trades_anlz.won.total / total_trades) * 100
        else:
            win_rate = 0.0
            
        metrics = {
            "Total Return (%)": round(tot_return, 2),
            "Win Rate (%)": round(win_rate, 2),
            "Max Drawdown (%)": round(max_dd, 2),
            "Total Trades": total_trades
        }
        
        return True, metrics

    except Exception as e:
        return False, f"Backtrader 엔진 자체 에러: {str(e)}"

def run_vectorbt(code_str: str, data: pd.DataFrame):
    """Vectorbt를 이용한 동적 백테스트 실행"""
    # 전역 접근용으로 data 할당
    local_env = {'data': data}
    
    try:
        exec(code_str, globals(), local_env)
        
        metrics = local_env.get('metrics')
        if not metrics or not isinstance(metrics, dict):
            return False, "스크립트가 올바른 'metrics' 딕셔너리를 생성하지 않았습니다. 템플릿의 끝부분을 확인해주세요."
            
        return True, metrics
        
    except Exception as e:
        return False, f"Vectorbt 엔진 파이프라인 에러: {str(e)}"

def run_backtest(engine: str, code_str: str, data: pd.DataFrame):
    if engine.lower() == 'backtrader':
        return run_backtrader(code_str, data)
    elif engine.lower() == 'vectorbt':
        return run_vectorbt(code_str, data)
    else:
        return False, "지원하지 않는 엔진입니다."
