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
from core.notifier import send_discord_alert, send_discord_error
from utils.exporter import create_excel_report
import redis

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

@celery_app.task(bind=True)
def run_optuna_worker(self, study_name: str, data_path: str, engine: str, code_str: str, n_trials: int, symbol: str):
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

        study.optimize(objective, n_trials=n_trials)
        status_redis.set(f"worker_status_{worker_id}", "완료됨", ex=300)
        return {"status": "worker_done"}
    except Exception as e:
        status_redis.set(f"worker_status_{worker_id}", f"치명적 오류: {str(e)}", ex=3600)
        return {"error": str(e)}

@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str):
    try:
        study = get_study(study_name)
        data = pd.read_pickle(data_path)
        
        # 🚨 고성능 엑셀 리포트 생성 (상위 50개 상세 데이터 포함)
        excel_output = create_excel_report(study, data)
        
        os.makedirs("results", exist_ok=True)
        file_path = f"results/Report_{study_name}.xlsx"
        with open(file_path, "wb") as f:
            f.write(excel_output.read())
            
        best_trial = study.best_trial
        send_discord_alert(study_name, best_trial.value, engine, symbol)
            
        return {"status": "SUCCESS", "best_value": best_trial.value, "excel_file": file_path}
    except Exception as e:
        send_discord_error(f"최종 집계 에러: {str(e)}", pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": str(e)}
