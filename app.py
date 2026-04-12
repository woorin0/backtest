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
from optuna.storages import JournalStorage
try:
    from optuna.storages import JournalRedisStorage
except ImportError:
    from optuna_integration.storages import JournalRedisStorage
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
    st.markdown("<h1 style='text-align: center;'>🔐 시스템 보안 인증</h1>", unsafe_allow_html=True)
    pwd = st.text_input("액세스 키", type="password")
    if st.button("인증"):
        if pwd == os.getenv("APP_PASSWORD", "jumbonuts"):
            st.session_state["logged_in"] = True
            st.rerun()
    st.stop()

# ----------------- [사이드바] -----------------
with st.sidebar:
    st.title("⚙️ Control Panel")
    eng = st.selectbox("엔진", ["Vectorbt", "Backtrader"], key="engine_sel")
    sym = st.text_input("심볼", "BTC/USDT")
    tf = st.selectbox("주기", ["1h", "4h", "15m"])
    trials = st.number_input("탐색수", 10, 10000, 100)
    workers = st.number_input("워커 수 (병렬 엔진)", 2, 8, 4)
    
    # 엔진 변경 시 코드 자동 리로드 (캐시 무시하고 파일에서 직독)
    def load_code(engine):
        try:
            if engine == "Vectorbt":
                with open("D:/Antigravity/백테스트 사용/백테스트 전략 코드(vectorbt).txt", "r", encoding="utf-8") as f:
                    return f.read()
            else:
                with open("D:/Antigravity/백테스트 사용/백테스트 전략 코드(backtrader).txt", "r", encoding="utf-8") as f:
                    return f.read()
        except:
            return ""

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
st.markdown("### 🛰️ 엔진 텔레메트리")
gauge_slot = st.empty()
status_slot = st.empty()
diag_slot = st.expander("🔍 워커 상세 진단", expanded=False)

st.divider()

# 📝 전략 에디터
st.markdown("### 📝 전략 알고리즘")
sc = st.text_area("Python Code", value=st.session_state.get("strategy_code", ""), height=350)
if sc != st.session_state.get("strategy_code"): st.session_state["strategy_code"] = sc

st.divider()

# 📜 히스토리
st.markdown("### 📜 리포트 아카이브 (최신 5개)")
res_files = sorted(glob.glob("results/*.xlsx"), key=os.path.getmtime, reverse=True)
for i, fp in enumerate(res_files[:5]):
    fn = os.path.basename(fp)
    with st.container():
        cols = st.columns([4, 1])
        cols[0].markdown(f"📁 **{fn}**")
        with open(fp, "rb") as f:
            cols[1].download_button("📥 다운로드", f, fn, key=f"dl_{i}")

# ----------------- [백그라운드 로직] -----------------
CACHE_FILE = ".active_task.json"
active_task = None
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: 
            meta = json.load(f)
        if meta and isinstance(meta, dict) and "task_id" in meta:
            task_check = AsyncResult(meta["task_id"], app=celery_app)
            if not task_check.ready(): 
                active_task = meta
            else: 
                os.remove(CACHE_FILE)
        else:
            os.remove(CACHE_FILE)
    except Exception:
        if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)

if btn_start and not active_task:
    from core.data_fetcher import fetch_candles, get_cache_path
    data = fetch_candles("Binance", sym, tf, datetime.date(2022,1,1), datetime.date.today(), 1000)
    if data is not None and not data.empty:
        dp = get_cache_path("Binance", sym, tf, datetime.date(2022,1,1), datetime.date.today())
        sn = f"study_{int(time.time())}"
        # 워커 시그니처 및 ID 사전 생성 (상태 추적용)
        worker_sigs = []
        worker_ids = []
        for _ in range(workers):
            w_id = uuid()
            sig = run_optuna_worker.s(sn, dp, eng, st.session_state["strategy_code"], trials//workers, sym, trials)
            sig.set(task_id=w_id)
            worker_sigs.append(sig)
            worker_ids.append(w_id)
            
        res = chord(worker_sigs)(finalize_optuna_study.s(sn, dp, eng, sym))
        active_task = {"task_id": res.id, "worker_ids": worker_ids, "study_name": sn, "n_trials": trials}
        with open(CACHE_FILE, "w") as f: json.dump(active_task, f)
        st.rerun()

if active_task:
    tk = AsyncResult(active_task["task_id"], app=celery_app)
    storage = JournalStorage(JournalRedisStorage("redis://localhost:6379/1"))
    
    @st.fragment(run_every=3)
    def monitor_progress():
        try:
            study = optuna.load_study(study_name=active_task.get("study_name"), storage=storage)
            compl = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
            
            # 베스트 전략 상세 지표 파싱
            best_val, best_win, best_mdd = 0.0, 0.0, 0.0
            if compl > 0:
                try:
                    best_trial = study.best_trial
                    best_val = best_trial.value if best_trial.value is not None else 0.0
                    best_win = best_trial.user_attrs.get('Win Rate (%)', 0.0)
                    best_mdd = best_trial.user_attrs.get('MDD (%)', 0.0)
                except: pass
            
            p_v = min(int(compl / active_task.get("n_trials", 1) * 100), 100)
            gauge_slot.progress(p_v, text=f"🚀 실시간 최적화 분석 중... {compl} / {active_task.get('n_trials')} ({p_v}%)")
            
            # 상단 4개 지표 카드 실시간 갱신
            draw_m(p_m1, "최고 수익률", f"{best_val:.2f}%", "#34C759")
            draw_m(p_m2, "최고 승률", f"{best_win:.2f}%", "#007aff")
            draw_m(p_m3, "최저 MDD", f"{best_mdd:.2f}%", "#FF3B30")
            draw_m(p_m4, "완료된 탐색", f"{compl} 회", "#5856D6")
            
            # 워커 상세 진단
            diag_text = ""
            for wid in active_task.get("worker_ids", []):
                stat = status_redis.get(f"worker_status_{wid}") or "⏳ 대기 중"
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
    
    # 작업 완료 후 처리
    try:
        final = tk.get(timeout=10)
        if final and final.get("status") == "SUCCESS":
            st.balloons()
            st.success(f"🏆 최적화 완료! 최고의 수익률: {final.get('best_value', 0.0):.2f}%")
            if final.get("excel_file") and os.path.exists(final["excel_file"]):
                with open(final["excel_file"], "rb") as f:
                    st.download_button("📥 상위 50개 상세 리포트 다운로드", f, os.path.basename(final["excel_file"]), type="primary")
            
            # 🚨 재시작을 위한 초기화 버튼
            if st.button("🧹 작업 초기화 및 다시 시작", use_container_width=True):
                if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
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
