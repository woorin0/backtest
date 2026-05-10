import streamlit as st
import os
import datetime
import math
import json
import time
import glob
import redis
from dotenv import load_dotenv
import optuna
from celery.result import AsyncResult
from celery import chord
from core.tasks import run_optuna_worker, finalize_optuna_study, celery_app
from core.notifier import send_discord_error
from celery import uuid

# 환경 변수 로드
load_dotenv()
status_redis = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)

st.set_page_config(page_title="퀀트 터미널 v3.0", page_icon="📈", layout="wide")

# ----------------- [섹션 1: 인증 시스템] -----------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    app_password = os.getenv("APP_PASSWORD")
    if not app_password:
        st.error("⚠️ 시스템 설정 오류: 'APP_PASSWORD' 환경 변수가 설정되지 않았습니다. 보안을 위해 서비스를 중단합니다.")
        st.stop()

    st.markdown("<h1 style='text-align: center;'>🔐 시스템 보안 인증</h1>", unsafe_allow_html=True)
    pwd = st.text_input("액세스 키", type="password")
    if st.button("인증"):
        if pwd == app_password:
            st.session_state["logged_in"] = True
            st.rerun()
    st.stop()

# ----------------- [사이드바] -----------------
with st.sidebar:
    st.title("⚙️ Control Panel")
    exc = st.selectbox("거래소", ["Binance", "Upbit"], key="exchange_sel")
    
    # 거래소에 따른 기본 심볼 설정
    default_sym = "BTC/USDT" if exc == "Binance" else "BTC/KRW"
    sym = st.text_input("심볼", default_sym, key="symbol_sel")
    
    eng = st.selectbox("엔진", ["Vectorbt", "Backtrader"], key="engine_sel")
    tf = st.selectbox("주기 (HTF)", ["15m", "30m", "1h", "2h", "4h"])
    ltf = st.selectbox("체결 정밀도 (LTF)", ["1m", "3m", "5m", "15m"], index=2)
    trials = st.number_input("탐색수", 10, 100000, 100)
    workers = st.number_input("워커 수 (병렬 엔진)", 2, 8, 4)
    repeat_count = st.number_input("반복수 (자동 연속 실행)", 1, 10, 1)
    
    st.markdown("---")
    st.markdown("📅 **백테스트 기간 설정**")
    d_col1, d_col2 = st.columns(2)
    with d_col1:
        date_start = st.date_input("시작일", datetime.date(2023, 1, 1))
    with d_col2:
        date_end = st.date_input("종료일", datetime.date.today())
    
    # 엔진 변경 시 코드 자동 리로드 (캐시 무시하고 파일에서 직독)
    # 엔진 변경 시 코드 자동 리로드 (캐시 무시하고 파일에서 직독)
    # 엔진 변경 시 코드 자동 리로드 (로컬/서버 공용 상대 경로 시스템)
    def load_code(engine):
        try:
            # os.getcwd()를 사용하여 현재 작업 디렉토리 기준 strategies 폴더 접근
            strategies_dir = os.path.join(os.getcwd(), "strategies")
            fn = f"{engine.lower()}.txt"
            target_path = os.path.join(strategies_dir, fn)
            
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    code = f.read()
                    if code.strip():
                        return code
            return f"# [Error] '{target_path}' 파일을 찾을 수 없거나 내용이 비어있습니다."
        except Exception as e:
            return f"# [Error] 코드 로드 실패: {str(e)}"

    if "prev_eng" not in st.session_state or st.session_state["prev_eng"] != eng:
        st.session_state["strategy_code"] = load_code(eng)
        st.session_state["prev_eng"] = eng

    st.markdown("---")
    st.warning("⚠️ 코드가 업데이트된 경우 반드시 아래 '최신 코드 불러오기'를 먼저 눌러주세요!")
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("🔄 최신 코드 불러오기"):
            st.session_state["strategy_code"] = load_code(eng)
            st.rerun()
    with c_btn2:
        btn_start = st.button("🚀 최적화 가동", type="primary")

# ----------------- [메인 화면] -----------------
st.title("📊 QUANTUM TERMINAL")

c1, c2, c3, c4 = st.columns(4)
p_m1, p_m2, p_m3, p_m4 = c1.empty(), c2.empty(), c3.empty(), c4.empty()

def draw_m(p, l, v, color="#007aff"):
    p.markdown(f"<div style='background: #f8f9fa; border-radius: 12px; padding: 15px; text-align: center; border: 1px solid #ddd; height: 110px;'><p style='color: #666; font-size: 0.9em; margin: 0;'>{l}</p><h2 style='color: {color}; margin: 5px 0; font-size: 1.6em;'>{v}</h2></div>", unsafe_allow_html=True)

st.divider()

# 🛰️ 엔진 모니터링 섹션 (진행률 강화)
# ----------------- [백그라운드 로직] -----------------
CACHE_FILE = ".active_task.json"
active_task = None
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: 
            meta = json.load(f)
        if meta and isinstance(meta, dict) and "task_id" in meta:
            # [V17] PREPARING 상태가 아닐 때만 실제 Celery 태스크 체크
            if meta["task_id"] != "PREPARING":
                task_check = AsyncResult(meta["task_id"], app=celery_app)
            active_task = meta
    except Exception:
        if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)

if active_task:
    sn = active_task["study_name"]
    
    # [V9.0] 데이터 수집 중 상태 모니터링
    if active_task.get("task_id") == "PREPARING":
        fetch_status = status_redis.get(f"data_fetch_status_{sn}")
        st.info(fetch_status if fetch_status else "백그라운드에서 데이터를 준비하고 있습니다...")
        if st.button("❌ 준비 중단"):
            if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
            st.rerun()
        time.sleep(2)
        st.rerun()
        
    st.markdown("### 🛰️ 엔진 텔레메트리")
gauge_slot = st.empty()
status_slot = st.empty()
diag_slot = st.expander("🔍 워커 상세 진단", expanded=False)

st.divider()

# 📝 전략 에디터
st.markdown("### 📝 전략 알고리즘")
# session_state["strategy_code"]와 직접 연동 (key 사용)
st.text_area("Python Code", key="strategy_code", height=350)

st.divider()

# 📜 히스토리
st.markdown("### 📜 리포트 아카이브 (최신 10개)")
res_files = sorted(glob.glob("results/*.xlsx"), key=os.path.getmtime, reverse=True)
for i, fp in enumerate(res_files[:10]):
    fn = os.path.basename(fp)
    with st.container():
        cols = st.columns([4, 1])
        cols[0].markdown(f"📁 **{fn}**")
        with open(fp, "rb") as f:
            cols[1].download_button("📥 다운로드", f, fn, key=f"dl_{i}")

if btn_start:
    # 🚀 [V19.2] 완료 상태에서 곧바로 최적화 가동 버튼을 누르면 찌꺼기 캐시를 파괴하고 즉시 시작
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    if "final_result" in st.session_state:
        del st.session_state["final_result"]
    active_task = None
    
    sn = f"study_{int(time.time())}"
    
    # 🚀 [V9.0] 데이터 수집 및 최적화를 백그라운드 태스크 하나로 묶어 발사
    from core.tasks import prepare_mtf_data_task
    
    # 임시 상태 저장 (데이터 수집 중임을 알림)
    active_task_dict = {
        "task_id": "PREPARING", # 데이터 수집 중 상태 표시용 예약어
        "worker_ids": [],
        "study_name": sn,
        "n_trials": trials,
        "current_iter": 1,
        "total_iters": repeat_count,
        "params": {"exc": exc, "eng": eng, "sym": sym, "tf": tf}
    }
    
    with open(CACHE_FILE, "w") as f:
        json.dump(active_task_dict, f)
        
    # Celery 태스크 발사 (데이터 수집 -> 최적화 -> 집계까지 원스톱)
    prepare_mtf_data_task.delay(
        sn, exc, sym, tf, ltf, 
        date_start.strftime("%Y-%m-%d"), 
        date_end.strftime("%Y-%m-%d"), 
        st.session_state["strategy_code"], 
        trials, workers, repeat_count, eng
    )
    
    st.rerun()

if active_task:
    tk = AsyncResult(active_task["task_id"], app=celery_app)
    # 🚀 [V7.3] JournalRedisStorage를 폐기하고 무제한 용량의 SQLite 데이터베이스로 프론트엔드 연결
    storage = "sqlite:///optuna_results.db"
    
    @st.fragment(run_every=3)
    def monitor_progress():
        try:
            # 🚀 [V7.1] 성능 최적화: get_trials() 전수조사 대신 Redis 카운터 사용
            completed_val = status_redis.get(f"progress:{active_task.get('study_name')}")
            compl = int(completed_val) if completed_val else 0
            
            # 베스트 전략 상세 지표 파싱 (🚀 [V7.2] Redis 해시 직접 접근으로 O(1) 비용 처리)
            best_val, best_win, best_mdd = 0.0, 0.0, 0.0
            if compl > 0:
                best_cache = status_redis.hgetall(f"best_metrics:{active_task.get('study_name')}")
                if best_cache:
                    best_val = float(best_cache.get('value', 0.0))
                    best_win = float(best_cache.get('win_rate', 0.0))
                    best_mdd = float(best_cache.get('mdd', 0.0))
            
            p_v = min(int(compl / active_task.get("n_trials", 1) * 100), 100)
            cur_i = active_task.get("current_iter", 1)
            tot_i = active_task.get("total_iters", 1)
            iter_text = f"[{cur_i}/{tot_i}회차] " if tot_i > 1 else ""
            gauge_slot.progress(p_v, text=f"🚀 {iter_text}실시간 최적화 분석 중... {compl} / {active_task.get('n_trials')} ({p_v}%)")
            
            # 상단 4개 지표 카드 실시간 갱신
            draw_m(p_m1, "최고 수익률", f"{best_val:.2f}%", "#34C759")
            draw_m(p_m2, "최고 승률", f"{best_win:.2f}%", "#007aff")
            draw_m(p_m3, "최저 MDD", f"{best_mdd:.2f}%", "#FF3B30")
            draw_m(p_m4, "완료된 탐색", f"{compl} 회", "#5856D6")
            
            # 워커 상세 진단 (Redis MGET을 통한 N+1 문제 해결)
            diag_text = ""
            worker_ids = active_task.get("worker_ids", [])
            if worker_ids:
                keys = [f"worker_status_{wid}" for wid in worker_ids]
                stats = status_redis.mget(keys)
                for wid, stat in zip(worker_ids, stats):
                    stat = stat or "⏳ 대기 중"
                    diag_text += f"- **워커 {wid[:6]}**: {stat}\n"
            diag_slot.markdown(diag_text)
            
            if not tk.ready():
                if st.button("⛔ 실시간 백테스트 강제 중단", use_container_width=True, type="secondary"):
                    # 1. 태스크 취소 (Chord + Workers)
                    celery_app.control.revoke(active_task.get("task_id"), terminate=True)
                    for wid in active_task.get("worker_ids", []):
                        celery_app.control.revoke(wid, terminate=True)
                    # 2. 캐시 삭제
                    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
                    st.success("🛰️ 모든 백그라운드 태스크를 강제 종료하고 리소스를 반환했습니다.")
                    time.sleep(1)
                    st.rerun()

            status_slot.info(f"📡 {active_task.get('study_name')} 세션이 {workers}개 코어를 풀가동 중입니다.")
            
            if tk.ready():
                st.rerun() # 작업 완료 시에만 전체 페이지 갱신
        except Exception as e:
            status_slot.warning(f"🔄 데이터 동기화 중... ({str(e)})")

    if not tk.ready():
        monitor_progress()
    else:
        # 완료 상태 표시를 위해 한 번 더 그리기
        try:
            study = optuna.load_study(study_name=active_task["study_name"], storage=storage)
            best_trial = study.best_trial
            draw_m(p_m1, "최고 수익률", f"{best_trial.value:.2f}%", "#34C759")
            draw_m(p_m2, "최고 승률", f"{best_trial.user_attrs.get('Win Rate (%)', 0.0):.2f}%", "#007aff")
            draw_m(p_m3, "최저 MDD", f"{best_trial.user_attrs.get('MDD (%)', 0.0):.2f}%", "#FF3B30")
            draw_m(p_m4, "탐색 종료", f"{len(study.get_trials())} 회", "#000000")
        except: pass
    
    # 🏁 작업 완료 후 처리 (로직 교정: tk.ready()일 때만 진입하여 프리징 방지)
    if tk.ready():
        try:
            # 결과를 세션에 캐싱하여 중복 get() 호출 방지
            if "final_result" not in st.session_state:
                with st.status("📊 최종 리포트 집계 및 엑셀 생성 중... (대량 데이터의 경우 최대 3분 소요)", expanded=True):
                    # 🚀 [V7.1] 대량 데이터 처리 시간 고려 타임아웃 연장 (60s -> 180s)
                    st.session_state["final_result"] = tk.get(timeout=180)
            
            final = st.session_state["final_result"]
            cur_i = active_task.get("current_iter", 1)
            tot_i = active_task.get("total_iters", 1)
            
            if final and final.get("status") == "SUCCESS":
                st.balloons()
                st.success(f"🏆 {cur_i}/{tot_i}회차 최적화 완료! 최고의 수익률: {final.get('best_value', 0.0):.2f}%")
                if final.get("excel_file") and os.path.exists(final["excel_file"]):
                    with open(final["excel_file"], "rb") as f:
                        btn_txt = f"📥 {cur_i}/{tot_i}회차 상세 리포트 다운로드" if tot_i > 1 else "📥 상세 리포트 다운로드"
                        st.download_button(btn_txt, f, os.path.basename(final["excel_file"]), type="primary")
                
                if tot_i > 1: 
                    st.success("✅ 지정된 모든 회차의 연속 실행이 완료되었습니다. 화면 좌측 하단 [리포트 아카이브]를 확인하세요.")
                # 🚨 재시작을 위한 초기화 버튼
                if st.button("Sweep & Restart (새 연구 시작)", use_container_width=True):
                    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
                    if "final_result" in st.session_state: del st.session_state["final_result"]
                    st.rerun()
        except Exception as e:
            status_slot.error(f"❌ 작업 결과 처리 중 오류: {str(e)}")
            if st.button("🚨 시스템 강제 초기화 (태스크 포함)", use_container_width=True):
                if active_task:
                    celery_app.control.revoke(active_task.get("task_id"), terminate=True)
                    for wid in active_task.get("worker_ids", []):
                        celery_app.control.revoke(wid, terminate=True)
                if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
                st.rerun()
else:
    draw_m(p_m1, "최고 수익률", "0.00%")
    draw_m(p_m4, "진행률", "준비 완료")
    status_slot.success("✅ 새로운 백테스트를 시작할 준비가 되었습니다.")
