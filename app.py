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

# 환경 변수 로드
load_dotenv()

# Redis 연결 (상태 진단용)
status_redis = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)

# 페이지 설정
st.set_page_config(page_title="퀀트 터미널 v2", page_icon="📈", layout="wide")

# ----------------- [CSS: 라이트 테마 & 모바일 최적화] -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; background-color: #ffffff !important; }
    .metric-card { background-color: #f8f9fa; border: 1px solid #e5e5ea; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .main-title { font-weight: 900; color: #007aff; text-align: center; margin-bottom: 30px; }
    div.stButton > button { border-radius: 8px; font-weight: 700; height: 3.5em; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ----------------- [섹션 1: 로그인 시스템 (Ghosting 박멸)] -----------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

def login_screen():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>🔐 시스템 인증 하세요</h1>", unsafe_allow_html=True)
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        pwd_input = st.text_input("액세스 키 입력", type="password", key="login_pwd")
        if st.button("시스템 인증 시작", key="login_btn"):
            if pwd_input == os.getenv("APP_PASSWORD", "jumbonuts"):
                st.session_state["logged_in"] = True
                st.rerun() # 즉시 화면 갱신하여 버튼 잔상 제거
            else:
                st.error("비밀번호가 올바르지 않습니다.")

def main_dashboard():
    # ----------------- [사이드바 설정] -----------------
    with st.sidebar:
        st.markdown("### 🛠️ 엔진 설정")
        with st.expander("구동 환경", expanded=True):
            exch = st.selectbox("거래소", ["Binance", "Upbit", "Bybit"])
            sym = st.text_input("심볼", "BTC/USDT")
            eng = st.selectbox("엔진", ["Vectorbt", "Backtrader"])
        with st.expander("세부 옵션", expanded=True):
            tf = st.selectbox("주기", ["1h", "4h", "15m", "1m"])
            sd = st.date_input("시작", datetime.date(2022, 1, 1))
            ed = st.date_input("종료", datetime.date.today())
            trials = st.number_input("시도수", 10, 10000, 100)
            workers = st.radio("워커", [2, 4, 8], index=1)
        st.markdown("---")
        if st.button("🚀 최적화 가동", type="primary"):
            st.session_state["start_opt"] = True

    # ----------------- [메인 화면] -----------------
    st.markdown("<h1 class='main-title'>📈 QUANTUM BACKTEST TERMINAL</h1>", unsafe_allow_html=True)
    
    # 지표 카드
    c1, c2, c3, c4 = st.columns(4)
    p_m1, p_m2, p_m3, p_m4 = c1.empty(), c2.empty(), c3.empty(), c4.empty()
    
    def draw_m(p, l, v, color="#121212"):
        p.markdown(f"<div class='metric-card'><p style='color: #888; font-size: 0.8em; margin: 0;'>{l}</p><h2 style='color: {color}; margin: 5px 0;'>{v}</h2></div>", unsafe_allow_html=True)
    
    draw_m(p_m1, "최고 수익률", "0.00%")
    draw_m(p_m2, "승률", "0.00%")
    draw_m(p_m3, "최대 낙폭", "0.00%")
    draw_m(p_m4, "진행률", "0 / 0")

    st.divider()

    # 모니터링 섹션
    st.markdown("### 🛰️ 실시간 엔진 텔레메트리")
    gauge_slot = st.empty()
    status_slot = st.empty()
    # 워커별 상세 진단 (0% 정체 해결용)
    with st.expander("👨‍💻 개별 워커 진단 데이터", expanded=True):
        worker_diag_slot = st.empty()

    st.divider()

    # 에디터 및 히스토리
    st.markdown("### 📝 전략 코드")
    if "strategy_code" not in st.session_state:
        from core.templates import VECTORBT_STRATEGY
        st.session_state["strategy_code"] = VECTORBT_STRATEGY
    sc = st.text_area("Python Code", value=st.session_state["strategy_code"], height=300)
    if sc != st.session_state["strategy_code"]: st.session_state["strategy_code"] = sc

    st.divider()

    # 🚨 히스토리 목록 (최신 3개 강제 고정)
    st.markdown("### 📜 리포트 아카이브 (최신 3개)")
    res_files = sorted(glob.glob("results/*.xlsx"), key=os.path.getmtime, reverse=True)
    for i, fp in enumerate(res_files[:3]):
        fn = os.path.basename(fp)
        with st.container():
            st.markdown(f"<div style='background: #f8f9fa; padding: 10px; border-radius: 8px; border-left: 5px solid #007aff; margin-bottom: 5px;'>{fn}</div>", unsafe_allow_html=True)
            with open(fp, "rb") as f:
                st.download_button(f"📥 다운로드", f, fn, key=f"hist_fix_{i}", use_container_width=True)
    
    if len(res_files) > 3:
        with st.expander("과거 내역 더보기"):
            for i, fp in enumerate(res_files[3:15]):
                fn = os.path.basename(fp)
                with open(fp, "rb") as f: st.download_button(f"📄 {fn}", f, fn, key=f"hist_plus_{i}")

    # ----------------- [백그라운드 제어 로직] -----------------
    CACHE_FILE = ".active_task.json"
    active_task = None
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f: meta = json.load(f)
            task_check = AsyncResult(meta["task_id"], app=celery_app)
            if not task_check.ready(): active_task = meta
            else: os.remove(CACHE_FILE)
        except: pass

    if st.session_state.get("start_opt") and not active_task:
        from core.data_fetcher import fetch_candles, get_cache_path
        with st.spinner("📦 데이터 수집 중..."):
            data = fetch_candles(exch, sym, tf, sd, ed, 1000)
        if data is not None and not data.empty:
            dp = get_cache_path(exch, sym, tf, sd, ed)
            sn = f"study_{int(time.time())}"
            # 워커 ID 추적을 위해 시그니처 생성
            worker_sigs = [run_optuna_worker.s(sn, dp, eng, st.session_state["strategy_code"], trials//workers, sym) for _ in range(workers)]
            res = chord(worker_sigs)(finalize_optuna_study.s(sn, dp, eng, sym))
            # 워커 ID들을 저장하여 개별 모니터링
            active_task = {"task_id": res.id, "worker_ids": [s.id for s in worker_sigs], "study_name": sn, "n_trials": trials, "start_at": time.time()}
            with open(CACHE_FILE, "w") as f: json.dump(active_task, f)
            st.session_state["start_opt"] = False
            st.rerun()

    if active_task:
        tk = AsyncResult(active_task["task_id"], app=celery_app)
        
        # [중단 버튼]
        if st.button("🛑 즉시 중단", type="secondary"):
            celery_app.control.revoke(active_task["task_id"], terminate=True)
            for wid in active_task.get("worker_ids", []): celery_app.control.revoke(wid, terminate=True)
            if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
            st.rerun()

        while not tk.ready():
            try:
                # 1. 워커별 실시간 진단 데이터 수집 (Redis DB 2)
                diag_text = ""
                for wid in active_task.get("worker_ids", []):
                    status = status_redis.get(f"worker_status_{wid}") or "대기 중 (Pending)"
                    diag_text += f"- **워커 {wid[:8]}**: {status}\n"
                worker_diag_slot.markdown(diag_text)

                # 2. 전역 성과 수집 (Optuna Redis DB 1)
                storage = JournalStorage(JournalRedisStorage("redis://localhost:6379/1"))
                study = optuna.load_study(study_name=active_task["study_name"], storage=storage)
                compl = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
                best = study.best_value if compl > 0 else 0.0
                
                p_v = min(int(compl / active_task["n_trials"] * 100), 100)
                gauge_slot.progress(p_v, text=f"진행: {compl} / {active_task['n_trials']}")
                draw_m(p_m1, "최고 수익률", f"{best:.2f}%", "#34C759" if best > 0 else "#121212")
                draw_m(p_m4, "진행률", f"{compl} / {active_task['n_trials']}")
                
                status_slot.info(f"🛰️ 엔진 가동 중: 최고의 수익 파라미터를 탐색하고 있습니다.")
            except: pass
            time.sleep(3)
        
        # 완료 처리
        try:
            final = tk.get(timeout=5)
            if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
            if final.get("status") == "SUCCESS":
                st.balloons()
                st.success(f"🏆 최적화 완료: 최종 {final['best_value']:.2f}%")
                with open(final["excel_file"], "rb") as f:
                    st.download_button("📥 최종 리포트 다운로드", f, f"Best_{active_task['study_name']}.xlsx", type="primary")
        except: pass

# --- 최종 레이아웃 분기 (잔상 방지 핵심) ---
if not st.session_state["logged_in"]:
    login_screen()
else:
    main_dashboard()
