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
from utils.exporter import create_excel_buffer

celery_app = Celery(
    'backtest_worker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

from celery import chord

def get_study(study_name):
    """Pruner가 적용된 Study 객체 생성"""
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    # MedianPruner: 중간 성적이 하위 50%인 경우 조기 종료하여 시간 단축
    return optuna.create_study(
        study_name=study_name, 
        storage=storage, 
        direction="maximize", 
        load_if_exists=True,
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=5)
    )

@celery_app.task(bind=True)
def run_optuna_worker(self, study_name: str, data_path: str, engine: str, code_str: str, n_trials: int, symbol: str):
    try:
        # 워커 내 중복 수집 방지: 전달받은 캐시 경로에서 데이터 직접 로드
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"캐시 데이터를 찾을 수 없습니다: {data_path}")
            
        data = pd.read_pickle(data_path)
        study = get_study(study_name)
        
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
    except Exception as e:
        err_msg = f"워커 실행 중 예외 발생: {str(e)}"
        send_discord_error(err_msg, pair=symbol, engine=engine)
        return {"error": err_msg}


@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str):
    try:
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"최종 리포트용 캐시 데이터를 찾을 수 없습니다: {data_path}")
            
        data = pd.read_pickle(data_path)
        study = get_study(study_name)
        
        trials = study.trials
        complete_trials = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
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
            excel_buf = create_excel_buffer(data, top_configs)
            os.makedirs("results", exist_ok=True)
            file_path = f"results/best_{self.request.id}.xlsx"
            with open(file_path, "wb") as f:
                f.write(excel_buf.read())
                
            return {"status": "SUCCESS", "study_name": study_name, "best_value": best_trial.value, "excel_file": file_path}
        
        return {"status": "FAILED", "reason": "완료된 Trial이 없습니다."}

    except Exception as e:
        err_msg = f"최종 결과 취합 중 오류 발생: {str(e)}"
        send_discord_error(err_msg, pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": err_msg}
