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
st.set_page_config(page_title="최첨단 퀀트 터미널 v2.2", page_icon="💻", layout="wide")

# ----------------- [섹션 1: 인증 시스템] -----------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown("<h1 style='text-align: center;'>🔐 시스템 보안 인증</h1>", unsafe_allow_html=True)
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        pwd = st.text_input("액세스 키", type="password", key="auth_pwd")
        if st.button("인증"):
            if pwd == os.getenv("APP_PASSWORD", "jumbonuts"):
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("비정상 접근")
    st.stop()

# ----------------- [사이드바] -----------------
with st.sidebar:
    st.title("⚙️ Control Panel")
    with st.expander("구동 환경", expanded=True):
        exch = st.selectbox("거래소", ["Binance", "Upbit"])
        sym = st.text_input("심볼", "BTC/USDT")
        # 🚨 엔진 선택 시 코드 자동 교체를 위한 로직 준비
        eng = st.selectbox("엔진", ["Vectorbt", "Backtrader"], key="engine_selector")
    
    with st.expander("세부 옵션", expanded=True):
        tf = st.selectbox("주기", ["1h", "4h", "15m"])
        sd = st.date_input("시작", datetime.date(2022, 1, 1))
        ed = st.date_input("종료", datetime.date.today())
        trials = st.number_input("탐색수", 10, 10000, 100)
        workers = st.radio("워커수", [2, 4, 8], index=1)
    st.markdown("---")
    btn_start = st.button("🚀 최적화 가동", type="primary")

# 🚨 [엔진 변경 감지 및 코드 자동 로드] 🚨
if "prev_eng" not in st.session_state:
    st.session_state["prev_eng"] = eng

# 엔진이 변경되었다면 해당 템플릿으로 강제 교체
if eng != st.session_state["prev_eng"]:
    from core.templates import VECTORBT_STRATEGY, BACKTRADER_STRATEGY
    st.session_state["strategy_code"] = VECTORBT_STRATEGY if eng == "Vectorbt" else BACKTRADER_STRATEGY
    st.session_state["prev_eng"] = eng
    st.rerun() # 코드 반영을 위해 화면 재렌더링

# ----------------- [메인 대시보드] -----------------
st.title("📊 QUANT TERMINAL")

# 지표 카드 섹션
c1, c2, c3, c4 = st.columns(4)
p_m1, p_m2, p_m3, p_m4 = c1.empty(), c2.empty(), c3.empty(), c4.empty()

def draw_m(p, l, v, color="#007aff"):
    p.markdown(f"<div style='background: #f8f9fa; border-radius: 12px; padding: 15px; text-align: center; border: 1px solid #ddd;'><p style='color: #666; margin: 0;'>{l}</p><h2 style='color: {color}; margin: 5px 0;'>{v}</h2></div>", unsafe_allow_html=True)

draw_m(p_m1, "최고 수익", "0.00%")
draw_m(p_m4, "진행률", "0 / 0")

st.divider()

# 🛰️ 엔진 텔레메트리 (상태 모니터링)
st.markdown("### 🛰️ 엔진 모니터링")
gauge_slot = st.empty()
status_slot = st.empty()

with st.expander("🔬 워커 상세 진단 데이터 (정체 시 확인)", expanded=False):
    worker_diag_slot = st.empty()
    if st.checkbox("🆘 조치 가이드 보기"):
        st.code("sudo systemctl restart celery-worker", language="bash")

st.divider()

# 📝 전략 에디터 (동적 코드 바인딩)
st.markdown("### 📝 전략 알고리즘")
if "strategy_code" not in st.session_state:
    from core.templates import VECTORBT_STRATEGY
    st.session_state["strategy_code"] = VECTORBT_STRATEGY

sc = st.text_area("Python Code Input", value=st.session_state["strategy_code"], height=350)
if sc != st.session_state["strategy_code"]: 
    st.session_state["strategy_code"] = sc

st.divider()

# 📜 히스토리 (최신 3개 고정)
st.markdown("### 📜 리포트 아카이브")
res_files = sorted(glob.glob("results/*.xlsx"), key=os.path.getmtime, reverse=True)
for i, fp in enumerate(res_files[:3]):
    fn = os.path.basename(fp)
    with st.container():
        st.markdown(f"📁 **{fn}**")
        with open(fp, "rb") as f:
            st.download_button(f"📥 다운로드 {i}", f, fn, key=f"dl_sys_bt_{i}", use_container_width=True)

# ----------------- [최적화 로직 및 모니터링] -----------------
CACHE_FILE = ".active_task.json"
active_task = None
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: meta = json.load(f)
        task_check = AsyncResult(meta["task_id"], app=celery_app)
        if not task_check.ready(): active_task = meta
        else: os.remove(CACHE_FILE)
    except: pass

if btn_start and not active_task:
    from core.data_fetcher import fetch_candles, get_cache_path
    with st.spinner("📦 시장 데이터 수집 중..."):
        data = fetch_candles(exch, sym, tf, sd, ed, 1000)
    if data is not None and not data.empty:
        dp = get_cache_path(exch, sym, tf, sd, ed)
        sn = f"study_{int(time.time())}"
        worker_sigs = [run_optuna_worker.s(sn, dp, eng, st.session_state["strategy_code"], trials//workers, sym) for _ in range(workers)]
        res = chord(worker_sigs)(finalize_optuna_study.s(sn, dp, eng, sym))
        active_task = {"task_id": res.id, "worker_ids": [s.id for s in worker_sigs], "study_name": sn, "n_trials": trials}
        with open(CACHE_FILE, "w") as f: json.dump(active_task, f)
        st.rerun()

if active_task:
    tk = AsyncResult(active_task["task_id"], app=celery_app)
    storage = JournalStorage(JournalRedisStorage("redis://localhost:6379/1"))
    
    while not tk.ready():
        try:
            diag_text = ""
            for wid in active_task.get("worker_ids", []):
                stat = status_redis.get(f"worker_status_{wid}") or "⏳ 대기 대기"
                diag_text += f"**워커 {wid[:6]}**: {stat}\n\n"
            worker_diag_slot.markdown(diag_text)

            study = optuna.load_study(study_name=active_task["study_name"], storage=storage)
            compl = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
            best = study.best_value if compl > 0 else 0.0
            p_v = min(int(compl / active_task["n_trials"] * 100), 100)
            gauge_slot.progress(p_v, text=f"진행: {compl}/{active_task['n_trials']}")
            draw_m(p_m1, "최고 수익", f"{best:.2f}%", "#34C759")
            draw_m(p_m4, "진행률", f"{compl}/{active_task['n_trials']}")
        except: pass
        time.sleep(3)
    st.rerun()
