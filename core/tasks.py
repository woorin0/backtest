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
from core.engine_runner import run_backtest
from core.notifier import send_discord_alert, send_discord_error, send_discord_progress
from utils.exporter import create_excel_report
import redis
import json
import subprocess
import sys

# [자가 치유] 필수 모듈 xlsxwriter 부재 시 자동 설치
try:
    import xlsxwriter
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "xlsxwriter"])
    import xlsxwriter

# Redis 연결 설정
status_redis = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)

celery_app = Celery(
    'backtest_worker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

def get_study(study_name):
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    return optuna.create_study(study_name=study_name, storage=storage, direction="maximize", load_if_exists=True)

class ProgressCallback:
    """전역 진행률을 체크하여 25/50/75% 시점에 디스코드 알림을 보내는 콜백 (중복 방지)"""
    def __init__(self, study_name, symbol, total_trials):
        self.study_name = study_name
        self.symbol = symbol
        self.total_trials = total_trials
        self.thresholds = [25, 50, 75]

    def __call__(self, study, trial):
        # 1. 전역 완료된 시도 횟수 확인
        completed_trials = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
        current_pct = int((completed_trials / self.total_trials) * 100)
        
        # 2. 임계값 도달 여부 체크
        for th in self.thresholds:
            if current_pct >= th:
                # Redis를 이용해 해당 구간 알림이 이미 전송되었는지 확인 (Distributed Lock)
                lock_key = f"alert_lock:{self.study_name}:{th}"
                if status_redis.setnx(lock_key, "sent"):
                    # 락 획득 성공 시 알림 전송 (만료시간 1시간 설정하여 자동 청소)
                    status_redis.expire(lock_key, 3600)
                    best_val = study.best_value if completed_trials > 0 else 0.0
                    send_discord_progress(self.study_name, self.symbol, th, best_val)

@celery_app.task(bind=True)
def run_optuna_worker(self, study_name: str, data_path: str, engine: str, code_str: str, n_trials: int, symbol: str, total_trials: int):
    worker_id = self.request.id
    error_notified = False
    
    try:
        data = pd.read_pickle(data_path)
        study = get_study(study_name)
        
        def objective(trial):
            nonlocal error_notified
            status_redis.set(f"worker_status_{worker_id}", f"최적화 중 ({trial.number}/{n_trials})", ex=600)
            
            success, res = run_backtest(engine, code_str, data, optuna_trial=trial)
            
            if success and isinstance(res, dict):
                # 성공 시 지표 저장
                trial.set_user_attr('Win Rate (%)', res.get('Win Rate (%)', 0.0))
                trial.set_user_attr('MDD (%)', res.get('MDD (%)', 0.0))
                trial.set_user_attr('Total Trades', res.get('Total Trades', 0))
                trial.set_user_attr('Total Profit', res.get('Total Profit', 0.0))
                return float(res.get("Total Return (%)", 0.0))
            else:
                # 🚨 -999.0 대신 Pruned 처리하여 결과 오염 방지
                if not error_notified:
                    send_discord_error(f"전략 에러 발생: {str(res)}", pair=symbol, engine=engine)
                    error_notified = True
                raise optuna.TrialPruned()

        study.optimize(objective, n_trials=n_trials, callbacks=[ProgressCallback(study_name, symbol, total_trials)])
        status_redis.set(f"worker_status_{worker_id}", "완료됨", ex=300)
        return {"status": "worker_done"}
    except Exception as e:
        status_redis.set(f"worker_status_{worker_id}", f"치명적 오류: {str(e)}", ex=3600)
        return {"error": str(e)}

@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str):
    # [방어 로직] 실행 시점에 한 번 더 체크
    try: import xlsxwriter
    except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", "xlsxwriter"])
    
    try:
        study = get_study(study_name)
        data = pd.read_pickle(data_path)
        
        # 🚨 고성능 엑셀 리포트 생성 (상위 50개 상세 데이터 포함)
        excel_output = create_excel_report(study, data)
        
        os.makedirs("results", exist_ok=True)
        file_path = f"results/Report_{study_name}.xlsx"
        with open(file_path, "wb") as f:
            f.write(excel_output.read())
            
        try:
            best_trial = study.best_trial
            best_value = best_trial.value
        except ValueError:
            # 시도가 하나도 없거나 모두 실패한 경우
            best_value = 0.0
            
        send_discord_alert(study_name, best_value, engine, symbol)
            
        return {"status": "SUCCESS", "best_value": best_value, "excel_file": file_path}
    except Exception as e:
        send_discord_error(f"최종 집계 에러: {str(e)}", pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": str(e)}
