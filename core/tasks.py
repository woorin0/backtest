import os
import time
import pandas as pd
from celery import Celery
import optuna
from optuna.storages import JournalStorage
try:
    from optuna.storages import JournalRedisStorage
except ImportError:
    from optuna_integration.storages import JournalRedisStorage
from core.data_fetcher import fetch_candles
from core.engine_runner import run_backtest
from core.notifier import send_discord_alert
from utils.exporter import create_excel_buffer

celery_app = Celery(
    'backtest_worker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

from celery import chord

@celery_app.task(bind=True)
def run_optimization_task(self, exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str, limit: int, engine: str, code_str: str, n_trials: int):
    # 1. 데이터 수집
    data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, progress_bar=None)
    if data is None or data.empty:
        return {"status": "FAILED", "reason": "데이터 수집 실패"}

    # 2. Redis 기반 Optuna 저장소 설정
    study_name = f"study_{self.request.id}"
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    study = optuna.create_study(study_name=study_name, storage=storage, direction="maximize", load_if_exists=True)
    
    # 3. 최적화 목표 정의 (objective)
    def objective(trial):
        success, metrics_or_err = run_backtest(engine, code_str, data, optuna_trial=trial)
        if success and isinstance(metrics_or_err, dict):
            trial.set_user_attr('Win Rate (%)', metrics_or_err.get('Win Rate (%)', 0.0))
            trial.set_user_attr('MDD (%)', metrics_or_err.get('MDD (%)', 0.0))
            trial.set_user_attr('Total Trades', metrics_or_err.get('Total Trades', 0))
            trial.set_user_attr('Total Profit', metrics_or_err.get('Total Profit', 0.0))
            return float(metrics_or_err.get("Total Return (%)", -999.0))
        else:
            raise optuna.TrialPruned()

    # 4. 최적화 실행
    study.optimize(objective, n_trials=n_trials)
    
    # 5. 결과 필터링 (승률 >= 60, MDD <= 30)
    trials = study.trials
    complete_trials = []
    for t in trials:
        if t.state == optuna.trial.TrialState.COMPLETE:
            wr = t.user_attrs.get('Win Rate (%)', 0)
            mdd = t.user_attrs.get('MDD (%)', 100)
            if wr >= 60.0 and mdd <= 30.0:
                complete_trials.append(t)
    
    # 정렬
    complete_trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    
    if not complete_trials:
        return {"status": "FAILED", "reason": f"조건(승률60/MDD30)에 부합하는 결과가 없습니다. (총 {len(trials)}회 탐색 완료)"}

    # 6. Top 50 결과 가공
    top_50 = complete_trials[:50]
    top_configs = []
    for t in top_50:
        top_configs.append({
            "Total Return (%)": t.value,
            "Win Rate (%)": t.user_attrs.get('Win Rate (%)', 0),
            "MDD (%)": t.user_attrs.get('MDD (%)', 0),
            "Total Trades": t.user_attrs.get('Total Trades', 0),
            "Total Profit": round(t.user_attrs.get('Total Profit', 0.0), 2),
            "params": t.params
        })
        
    # 7. 디스코드 알림 및 엑셀 생성
    best_trial = complete_trials[0]
    send_discord_alert(study_name, best_trial.value, engine, symbol)
    
    best_metrics = {
        "Total Return (%)": best_trial.value, 
        "Win Rate (%)": best_trial.user_attrs.get('Win Rate (%)', 0), 
        "Best Params": str(best_trial.params)
    }
    excel_buf = create_excel_buffer(data, top_configs)
    
    os.makedirs("results", exist_ok=True)
    file_path = f"results/best_{self.request.id}.xlsx"
    with open(file_path, "wb") as f:
        f.write(excel_buf.read())
        
    return {"status": "SUCCESS", "study_name": study_name, "best_value": best_trial.value, "excel_file": file_path}

@celery_app.task(bind=True, soft_time_limit=1500, time_limit=1800)
def run_optuna_worker(self, study_name: str, exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str, limit: int, engine: str, code_str: str, n_trials: int):
    data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, progress_bar=None)
    if data is None or data.empty:
        return {"error": "데이터 수집 실패"}

    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    study = optuna.create_study(study_name=study_name, storage=storage, direction="maximize", load_if_exists=True)
    
    def objective(trial):
        success, metrics_or_err = run_backtest(engine, code_str, data, optuna_trial=trial)
        if success and isinstance(metrics_or_err, dict):
            trial.set_user_attr('Win Rate (%)', metrics_or_err.get('Win Rate (%)', 0.0))
            trial.set_user_attr('MDD (%)', metrics_or_err.get('MDD (%)', 0.0))
            trial.set_user_attr('Total Trades', metrics_or_err.get('Total Trades', 0))
            trial.set_user_attr('Total Profit', metrics_or_err.get('Total Profit', 0.0))
            return float(metrics_or_err.get("Total Return (%)", -999.0))
        else:
            raise optuna.TrialPruned()

    study.optimize(objective, n_trials=n_trials)
    return {"status": "worker_done", "worker_id": self.request.id, "n_trials": n_trials}


@celery_app.task(bind=True, soft_time_limit=600, time_limit=900)
def finalize_optuna_study(self, worker_results, study_name: str, exchange: str, symbol: str, timeframe: str, start_date: str, end_date: str, limit: int, engine: str):
    # worker_results는 [결과1, 결과2, 결과3, 결과4] 리스트로 들어옴
    
    # 엑셀 생성을 위한 데이터 로드 (타임아웃 및 재시도 고려)
    try:
        data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, progress_bar=None)
        if data is None or data.empty:
            return {"status": "FAILED", "reason": "최종 결과 수집을 위한 데이터 로드 실패"}
    except Exception as e:
        return {"status": "FAILED", "reason": f"데이터 수신 중 오류 발생: {str(e)}"}
    
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    try:
        study = optuna.load_study(study_name=study_name, storage=storage)
    except Exception as e:
        return {"status": "FAILED", "reason": f"Optuna 스터디 로드 실패: {str(e)}"}
    
    trials = study.trials
    complete_trials = []
    for t in trials:
        if t.state == optuna.trial.TrialState.COMPLETE:
            wr = t.user_attrs.get('Win Rate (%)', 0)
            mdd = t.user_attrs.get('MDD (%)', 100)
            if wr >= 60.0 and mdd <= 30.0:
                complete_trials.append(t)
    complete_trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    
    top_50 = complete_trials[:50]
    top_configs = []
    for t in top_50:
        top_configs.append({
            "Total Return (%)": t.value,
            "Win Rate (%)": t.user_attrs.get('Win Rate (%)', 0),
            "MDD (%)": t.user_attrs.get('MDD (%)', 0),
            "Total Trades": t.user_attrs.get('Total Trades', 0),
            "Total Profit": round(t.user_attrs.get('Total Profit', 0.0), 2),
            "params": t.params
        })
        
    best_trial = complete_trials[0] if complete_trials else None
    
    if best_trial:
        send_discord_alert(study_name, best_trial.value, engine, symbol)
        
        best_metrics = {
            "Total Return (%)": best_trial.value, 
            "Win Rate (%)": best_trial.user_attrs.get('Win Rate (%)', 0), 
            "Best Params": str(best_trial.params)
        }
        excel_buf = create_excel_buffer(data, top_configs)
        
        os.makedirs("results", exist_ok=True)
        file_path = f"results/best_{self.request.id}.xlsx"
        with open(file_path, "wb") as f:
            f.write(excel_buf.read())
            
        return {"status": "SUCCESS", "study_name": study_name, "best_value": best_trial.value, "excel_file": file_path}
    
    return {"status": "FAILED", "reason": "조건(승률60/MDD30)에 부합하는 완료된 Trial이 없습니다."}
