import os
import time
import pandas as pd
from celery import Celery
import optuna
from optuna.storages import RDBStorage
from core.data_fetcher import fetch_candles
from core.engine_runner import run_backtest
from core.notifier import send_discord_alert
from utils.exporter import create_excel_buffer

celery_app = Celery(
    'backtest_worker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

@celery_app.task(bind=True)
def run_optimization_task(self, exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str, limit: int, engine: str, code_str: str, n_trials: int = 100):
    # 1. 과거 캔들 데이터 수집
    data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, progress_bar=None)
    
    if data is None or data.empty:
        return {"error": "데이터 수집 실패"}

    study_name = f"study_{self.request.id}"
    storage = RDBStorage("sqlite:///optuna_study.db")
    
    study = optuna.create_study(study_name=study_name, storage=storage, direction="maximize", load_if_exists=True)
    
    def objective(trial):
        success, metrics_or_err = run_backtest(engine, code_str, data, optuna_trial=trial)
        if success and isinstance(metrics_or_err, dict):
            # 성과와 기타 메트릭을 기록
            trial.set_user_attr('Win Rate (%)', metrics_or_err.get('Win Rate (%)', 0.0))
            trial.set_user_attr('MDD (%)', metrics_or_err.get('MDD (%)', 0.0))
            trial.set_user_attr('Total Trades', metrics_or_err.get('Total Trades', 0))
            trial.set_user_attr('Total Profit', metrics_or_err.get('Total Profit', 0.0))
            return float(metrics_or_err.get("Total Return (%)", -999.0))
        else:
            raise optuna.TrialPruned()

    # 옵튜나 최적화 진행 서치
    study.optimize(objective, n_trials=n_trials)
    
    # 완료 후 Top 30 결과 추출
    trials = study.trials
    complete_trials = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
    complete_trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    
    top_30 = complete_trials[:30]
    top_configs = []
    for t in top_30:
        top_configs.append({
            "Total Return (%)": t.value,
            "Win Rate (%)": t.user_attrs.get('Win Rate (%)', 0),
            "MDD (%)": t.user_attrs.get('MDD (%)', 0),
            "Total Trades": t.user_attrs.get('Total Trades', 0),
            "Total Profit": round(t.user_attrs.get('Total Profit', 0.0), 2),
            "params": t.params
        })
        
    best_trial = complete_trials[0] if complete_trials else None
    
    # 디스코드 알림 (완료 알림만 전송)
    if best_trial:
        send_discord_alert(study_name, best_trial.value, engine, symbol)
    
    # Best 1 결과에 대해 엑셀 기록 후 results 폴더에 저장
    if best_trial:
        best_metrics = {
            "Total Return (%)": best_trial.value, 
            "Win Rate (%)": best_trial.user_attrs.get('Win Rate (%)', 0), 
            "Best Params": str(best_trial.params)
        }
        excel_buf = create_excel_buffer(data, best_metrics, top_configs)
        
        os.makedirs("results", exist_ok=True)
        file_path = f"results/best_{self.request.id}.xlsx"
        with open(file_path, "wb") as f:
            f.write(excel_buf.read())
            
        return {"status": "SUCCESS", "study_name": study_name, "best_value": best_trial.value, "excel_file": file_path}
    
    return {"status": "FAILED", "reason": "완료된 Trial이 없습니다."}
