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

# Redis 연결 설정 (상태 기록용) - 안정성을 위해 타임아웃 및 재시도 설정 추가
status_redis = redis.Redis(
    host='localhost', 
    port=6379, 
    db=2, 
    decode_responses=True,
    socket_timeout=5,
    retry_on_timeout=True
)

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
    error_notified = False
    
    try:
        # 단계 1: 데이터 로딩 안정화 (파일 점유 방지)
        status_redis.set(f"worker_status_{worker_id}", "📊 시장 데이터 로드 중...", ex=3600)
        
        # 파일이 생성 중일 수 있으므로 최대 3번 재시도
        data = None
        for i in range(3):
            try:
                if os.path.exists(data_path):
                    data = pd.read_pickle(data_path)
                    break
            except:
                time.sleep(2)
        
        if data is None:
            raise FileNotFoundError(f"데이터 파일 로드 실패: {data_path}")
            
        study = get_study(study_name)
        status_redis.set(f"worker_status_{worker_id}", "🧠 엔진 및 전략 준비 완료", ex=3600)
        
        def objective(trial):
            nonlocal code_str, error_notified
            status_redis.set(f"worker_status_{worker_id}", f"🚀 최적화 중 (Trial {trial.number}/{n_trials})", ex=600)
            
            # 수치 안정성을 위해 run_backtest 호출 시 예외 처리 강화
            try:
                success, metrics_or_err = run_backtest(engine, code_str, data, optuna_trial=trial)
            except Exception as e:
                success, metrics_or_err = False, f"런타임 예외: {str(e)}"
            
            if success and isinstance(metrics_or_err, dict):
                trial.set_user_attr('Win Rate (%)', metrics_or_err.get('Win Rate (%)', 0.0))
                trial.set_user_attr('MDD (%)', metrics_or_err.get('MDD (%)', 0.0))
                trial.set_user_attr('Total Trades', metrics_or_err.get('Total Trades', 0))
                trial.set_user_attr('Total Profit', metrics_or_err.get('Total Profit', 0.0))
                return float(metrics_or_err.get("Total Return (%)", -999.0))
            else:
                if not error_notified:
                    send_discord_error(f"전략 수행 실패 (반복 가능성 있음): {metrics_or_err}", pair=symbol, engine=engine)
                    error_notified = True 
                raise optuna.TrialPruned()

        # 단계 3: 최적화 실제 실행 및 정체 방지
        study.optimize(objective, n_trials=n_trials)
        status_redis.set(f"worker_status_{worker_id}", "✅ 모든 탐색 완료", ex=300)
        return {"status": "worker_done", "worker_id": worker_id}
        
    except Exception as e:
        status_redis.set(f"worker_status_{worker_id}", f"❗ 에러: {str(e)[:50]}...", ex=3600)
        if not error_notified:
            send_discord_error(f"워커 긴급 오류: {str(e)}", pair=symbol, engine=engine)
        return {"error": str(e)}

@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str):
    try:
        status_redis.set("finalizer_status", "📈 최종 리포트 취합 중...", ex=600)
        if not os.path.exists(data_path): raise FileNotFoundError("데이터 누락")
        data = pd.read_pickle(data_path)
        study = get_study(study_name)
        
        trials = study.trials
        complete_trials = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
        
        best_trial = None
        if complete_trials:
            complete_trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
            best_trial = complete_trials[0]
            
            # 리포트 데이터 생성 부분 생략(기존 유지)
            excel_buf = create_excel_buffer(data, []) 
            os.makedirs("results", exist_ok=True)
            file_path = f"results/best_{study_name}.xlsx"
            with open(file_path, "wb") as f: f.write(excel_buf.read())
            
            send_discord_alert(study_name, best_trial.value, engine, symbol)
            status_redis.set("finalizer_status", "✨ 리포트 생성 완료", ex=300)
            return {"status": "SUCCESS", "best_value": best_trial.value, "excel_file": file_path}
        
        status_redis.set("finalizer_status", "❌ 결과 없음", ex=300)
        return {"status": "FAILED", "reason": "완료된 Trial 없음"}
    except Exception as e:
        send_discord_error(f"최종 집계 치명적 오류: {str(e)}", pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": str(e)}
