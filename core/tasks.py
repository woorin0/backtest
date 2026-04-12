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
import redis

# Redis 연결 설정 (상태 기록용)
status_redis = redis.Redis(host='localhost', port=6379, db=2)

celery_app = Celery(
    'backtest_worker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

def get_study(study_name):
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    sampler = optuna.samplers.TPESampler(multivariate=True, constant_liar=True)
    return optuna.create_study(
        study_name=study_name, 
        storage=storage, 
        direction="maximize", 
        load_if_exists=True,
        sampler=sampler,
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=5)
    )

@celery_app.task(bind=True)
def run_optuna_worker(self, study_name: str, data_path: str, engine: str, code_str: str, n_trials: int, symbol: str):
    worker_id = self.request.id
    try:
        # 단계 1: 데이터 로딩 시작
        status_redis.set(f"worker_status_{worker_id}", "데이터 로딩 중...", ex=3600)
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"데이터 파일 누락: {data_path}")
            
        data = pd.read_pickle(data_path)
        study = get_study(study_name)
        
        # 단계 2: 전략 준비
        status_redis.set(f"worker_status_{worker_id}", "엔진 및 전략 준비...", ex=3600)
        
        def objective(trial):
            nonlocal code_str
            # 실시간 체크포인트 업데이트 (현재 시도 횟수 기록)
            status_redis.set(f"worker_status_{worker_id}", f"최적화 중 (Trial {trial.number})", ex=600)
            
            success, metrics_or_err = run_backtest(engine, code_str, data, optuna_trial=trial)
            
            if success and isinstance(metrics_or_err, dict):
                trial.set_user_attr('Win Rate (%)', metrics_or_err.get('Win Rate (%)', 0.0))
                trial.set_user_attr('MDD (%)', metrics_or_err.get('MDD (%)', 0.0))
                trial.set_user_attr('Total Trades', metrics_or_err.get('Total Trades', 0))
                trial.set_user_attr('Total Profit', metrics_or_err.get('Total Profit', 0.0))
                return float(metrics_or_err.get("Total Return (%)", -999.0))
            else:
                # 에러 발생 시 디스코드로 상세 원인 전송
                send_discord_error(f"워커 전략 수행 실패: {str(metrics_or_err)}", pair=symbol, engine=engine)
                raise optuna.TrialPruned()

        # 단계 3: 최적화 루프 진입
        study.optimize(objective, n_trials=n_trials)
        status_redis.set(f"worker_status_{worker_id}", "완료됨", ex=300)
        return {"status": "worker_done", "worker_id": worker_id}
        
    except Exception as e:
        err_msg = f"워커 치명적 오류: {str(e)}"
        status_redis.set(f"worker_status_{worker_id}", f"에러: {str(e)}", ex=3600)
        send_discord_error(err_msg, pair=symbol, engine=engine)
        return {"error": err_msg}

@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str):
    try:
        status_redis.set("finalizer_status", "최종 리포트 생성 중...", ex=600)
        if not os.path.exists(data_path): raise FileNotFoundError("데이터 누락")
            
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
            status_redis.set("finalizer_status", "리포트 완성", ex=300)
            return {"status": "SUCCESS", "study_name": study_name, "best_value": best_trial.value, "excel_file": file_path}
        
        return {"status": "FAILED", "reason": "완료된 Trial 없음"}
    except Exception as e:
        send_discord_error(f"취합 오류: {str(e)}", pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": str(e)}
