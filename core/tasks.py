import os
import time
import pandas as pd
from celery import Celery
import optuna
from core.engine_runner import run_backtest
from core.notifier import send_discord_alert, send_discord_error, send_discord_progress
from core.data_fetcher import fetch_candles, get_cache_path, RedisProgress
from utils.exporter import create_excel_report
from utils.sheets import push_to_google_sheets
import redis
import json
import subprocess
import sys
import traceback

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
# [V14.1] Celery 워커 메모리 누수 방지
celery_app.conf.update(
    worker_max_tasks_per_child=5, 
    worker_prefetch_multiplier=1,
    task_acks_late=False # [V7.5] 메모리 부족 재시작 시 동일 작업 중복 실행(탐색수 오버) 방지
)

def get_study(study_name):
    # 🚀 [V7.3] JournalRedisStorage 완전 제거, 메모리 한계 없는 로컬 SQLite RDBMS 도입
    storage = "sqlite:///optuna_results.db"
    return optuna.create_study(study_name=study_name, storage=storage, direction="maximize", load_if_exists=True)

class ProgressCallback:
    """전역 진행률을 체크하여 25/50/75% 시점에 디스코드 알림을 보내는 콜백 (중복 방지)"""
    def __init__(self, study_name, symbol, total_trials):
        self.study_name = study_name
        self.symbol = symbol
        self.total_trials = total_trials
        self.thresholds = [25, 50, 75]

    def __call__(self, study, trial):
        # 1. Redis에서 전역 완료 횟수 가져오기 (성능 최적화: get_trials 전수조사 제거)
        completed_val = status_redis.get(f"progress:{self.study_name}")
        completed_trials = int(completed_val) if completed_val else 0
        current_pct = int((completed_trials / self.total_trials) * 100)
        
        # 2. 임계값 도달 여부 체크 (기존 로직 유지)
        for th in self.thresholds:
            if current_pct >= th:
                # Redis를 이용해 해당 구간 알림이 이미 전송되었는지 확인 (Distributed Lock)
                lock_key = f"alert_lock:{self.study_name}:{th}"
                if status_redis.setnx(lock_key, "sent"):
                    # 🚀 [V7.3] 락 획득 성공 시 알림 전송 (만료시간 7일로 대폭 연장하여 중복 발송 원천 차단)
                    status_redis.expire(lock_key, 86400 * 7)
                    best_val = study.best_value if completed_trials > 0 else 0.0
                    send_discord_progress(self.study_name, self.symbol, th, best_val)

@celery_app.task(bind=True)
def prepare_mtf_data_task(self, study_name: str, exchange: str, symbol: str, htf: str, ltf: str, 
                         start_date: str, end_date: str, code_str: str, trials: int, 
                         workers: int, repeat_count: int, engine: str):
    """[V9.0] 데이터 수집부터 최적화 가동까지 전체 프로세스를 백그라운드에서 실행"""
    from celery import uuid, chord
    progress_key = f"data_fetch_status_{study_name}"
    rp = RedisProgress(progress_key)
    
    try:
        # 1. HTF 데이터 수집
        rp.progress(5, f"HTF({htf}) 데이터 수집 중...")
        data_htf = fetch_candles(exchange, symbol, htf, start_date, end_date, 1000, progress_bar=rp, padding_candles=1000)
        
        # 2. LTF 데이터 수집
        rp.progress(50, f"LTF({ltf}) 데이터 수집 중...")
        data_ltf = fetch_candles(exchange, symbol, ltf, start_date, end_date, 1000, progress_bar=rp, padding_candles=0)
        
        if data_htf is None or data_ltf is None:
            raise Exception("데이터 수집 실패 (거래소 응답 없음)")

        # 3. 데이터 결합 및 저장
        rp.progress(90, "데이터 결합 및 저장 중...")
        dp_htf_cache = get_cache_path(exchange, symbol, htf, start_date, end_date, padding_candles=1000)
        data_path = f"{dp_htf_cache}_mtf.pkl"
        pd.to_pickle({'htf': data_htf, 'ltf': data_ltf}, data_path)
        
        # 4. 최적화 작업(Chord) 트리거
        rp.progress(100, "최적화 작업을 큐에 등록 중...")
        
        worker_sigs = []
        worker_ids = []
        for _ in range(workers):
            w_id = uuid()
            sig = run_optuna_worker.s(study_name, data_path, engine, code_str, trials//workers, symbol, trials)
            sig.set(task_id=w_id)
            worker_sigs.append(sig)
            worker_ids.append(w_id)
            
        active_task_dict = {
            "task_id": "", # chord id는 아래에서 할당
            "worker_ids": worker_ids,
            "study_name": study_name,
            "n_trials": trials,
            "current_iter": 1,
            "total_iters": repeat_count,
            "params": {
                "dp": data_path, "eng": engine, "code": code_str, 
                "trials": trials, "workers": workers, "sym": symbol, "tf": htf
            }
        }
        
        # 🚀 [V9.0] Chord 실행 및 ID 업데이트
        res = chord(worker_sigs)(finalize_optuna_study.s(study_name, data_path, engine, symbol, htf, active_task_dict))
        active_task_dict["task_id"] = res.id
        
        # UI 업데이트를 위해 .active_task.json 파일 갱신
        cache_file = ".active_task.json"
        with open(cache_file, "w") as f:
            json.dump(active_task_dict, f)
            
        rp.empty() # 작업 완료 후 상태 삭제
        return {"status": "SUCCESS", "study_name": study_name}
        
    except Exception as e:
        err_msg = f"데이터 준비 에러: {str(e)}"
        status_redis.set(progress_key, f"🚨 {err_msg}", ex=3600)
        send_discord_error(err_msg, pair=symbol, engine=engine)
        return {"status": "FAILED", "error": err_msg}

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
            
            # 🚀 [V7.5] 모든 워커가 합산 목표치(total_trials)를 초과하지 않도록 실시간 글로벌 체크
            current_progress = status_redis.get(f"progress:{study_name}")
            if current_progress and int(current_progress) >= total_trials:
                study.stop() # 현재 워커의 최적화 루프 중단
                return 0.0
            
            try:
                success, res = run_backtest(engine, code_str, data, optuna_trial=trial)
                
                if success and isinstance(res, dict):
                    # 성공 시 지표 저장 (🚀 [방어] 거대 객체 직렬화로 인한 커밋 에러 원천 차단)
                    def safe_set(key, val):
                        if isinstance(val, (int, float, str, bool)):
                            trial.set_user_attr(key, val)
                        else:
                            # 객체가 너무 클 경우 문자열로 요약만 저장
                            trial.set_user_attr(key, str(val)[:100])

                    safe_set('Win Rate (%)', res.get('Win Rate (%)', 0.0))
                    safe_set('MDD (%)', res.get('MDD (%)', 0.0))
                    safe_set('Total Trades', res.get('Total Trades', 0))
                    safe_set('Total Profit', res.get('Total Profit', 0.0))
                    
                    # 🚀 [V7.1] 실시간 고속 진행률 추적을 위한 Redis 카운터 증가
                    status_redis.incr(f"progress:{study_name}")
                    status_redis.expire(f"progress:{study_name}", 86400) # 24시간 후 자동 삭제
                    
                    ret_val = float(res.get("Total Return (%)", 0.0))
                    win_rate = res.get('Win Rate (%)', 0.0)
                    mdd = res.get('MDD (%)', 0.0)
                    
                    # 🚀 [V7.2] 최고 성능 지표 실시간 독립 캐싱 O(1)
                    best_key = f"best_metrics:{study_name}"
                    current_best = status_redis.hget(best_key, "value")
                    if current_best is None or ret_val > float(current_best):
                        status_redis.hset(best_key, mapping={
                            "value": float(ret_val),
                            "win_rate": float(win_rate),
                            "mdd": float(mdd)
                        })
                        status_redis.expire(best_key, 86400)
                    
                    return ret_val
                else:
                    # 🚨 에러 디버깅을 위해 로컬 파일에 로그 기록
                    with open("debug_error.log", "a", encoding="utf-8") as f:
                        f.write(f"TRIAL {trial.number} FAILED - RES: {str(res)}\n")
                        
                    if not error_notified:
                        send_discord_error(f"전략 에러 발생: {str(res)}", pair=symbol, engine=engine)
                        error_notified = True
                    raise optuna.TrialPruned()
            except Exception as e:
                with open("debug_error.log", "a", encoding="utf-8") as f:
                    f.write(f"TRIAL {trial.number} EXCEPTION - {str(e)}\n{traceback.format_exc()}\n")
                traceback.print_exc()
                raise optuna.TrialPruned()

        study.optimize(objective, n_trials=n_trials, callbacks=[ProgressCallback(study_name, symbol, total_trials)])
        status_redis.set(f"worker_status_{worker_id}", "완료됨", ex=300)
        return {"status": "worker_done"}
    except Exception as e:
        error_msg = str(e)
        # 🚨 [V7.3] 타임아웃 및 OOM 워커 강제 중단 발생 시 디스코드 즉시 알람
        try:
            send_discord_error(f"워커 강제 종료 또는 통신 단절 에러: {error_msg}", pair=symbol, engine=engine)
            status_redis.set(f"worker_status_{worker_id}", f"치명적 오류: {error_msg}", ex=3600)
        except: 
            pass # Redis마저 죽었을 경우 방어
            
        return {"error": error_msg}

@celery_app.task(bind=True)
def finalize_optuna_study(self, worker_results, study_name: str, data_path: str, engine: str, symbol: str, timeframe: str, active_task_dict: dict = None):
    # [방어 로직] 실행 시점에 한 번 더 체크
    try: import xlsxwriter
    except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", "xlsxwriter"])
    
    try:
        study = get_study(study_name)
        data = pd.read_pickle(data_path)
        
        # 🚨 고성능 엑셀 리포트 생성 (상위 50개 상세 데이터 포함)
        excel_output, report_df = create_excel_report(study, data)
        
        # 🚀 [V8.0] 구글 시트 전송
        try:
            push_to_google_sheets(report_df, engine, symbol, timeframe)
        except Exception as e:
            print(f"[Google Sheets Error] {str(e)}")
        
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
            
        # 🚨 [새로운 백엔드 자율 연속 실행 루프]
        # 브라우저 절전 모드로 인한 지연을 차단하기 위해, Celery 백엔드가 스스로 다음 회차를 발사합니다.
        if active_task_dict:
            cur_i = active_task_dict.get("current_iter", 1)
            tot_i = active_task_dict.get("total_iters", 1)
            if cur_i < tot_i:
                params = active_task_dict.get("params", {})
                from celery import uuid, chord
                import optuna
                
                next_sn = f"study_{int(time.time())}"
                optuna.create_study(study_name=next_sn, storage="sqlite:///optuna_results.db", direction="maximize", load_if_exists=True)
                
                worker_sigs = []
                worker_ids = []
                w_cnt = params.get("workers", 4)
                for _ in range(w_cnt):
                    w_id = uuid()
                    sig = run_optuna_worker.s(next_sn, params["dp"], params["eng"], params["code"], params["trials"]//w_cnt, params["sym"], params["trials"])
                    sig.set(task_id=w_id)
                    worker_sigs.append(sig)
                    worker_ids.append(w_id)
                
                next_active_task = active_task_dict.copy()
                next_active_task["current_iter"] = cur_i + 1
                next_active_task["study_name"] = next_sn
                next_active_task["worker_ids"] = worker_ids
                
                res = chord(worker_sigs)(finalize_optuna_study.s(next_sn, params["dp"], params["eng"], params["sym"], params["tf"], next_active_task))
                next_active_task["task_id"] = res.id
                
                # 디스크 파일 덮어쓰기 (프론트엔드가 깨어나면 이 파일을 읽고 최신 상태 인지)
                cache_file = os.path.join(os.getcwd(), ".active_task.json")
                with open(cache_file, "w") as f:
                    import json
                    json.dump(next_active_task, f)

        return {"status": "SUCCESS", "best_value": best_value, "excel_file": file_path}
    except Exception as e:
        send_discord_error(f"최종 집계 에러: {str(e)}", pair=symbol, engine=engine)
        return {"status": "FAILED", "reason": str(e)}
