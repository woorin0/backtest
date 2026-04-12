import streamlit as st
import os
import datetime
import math
import json
import time
import glob
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

# 프리미엄 페이지 설정
st.set_page_config(
    page_title="High-End Quant Dashboard",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- [CSS: Premium Aesthetics] -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Global Background */
    .stApp {
        background-color: #0e1117;
    }
    
    /* Card Styling (Glassmorphism) */
    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 15px;
        padding: 25px;
        text-align: center;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    .metric-card:hover {
        transform: translateY(-5px);
        border: 1px solid #f0c04a;
        background: rgba(240, 192, 74, 0.05);
    }
    
    /* Title Styling */
    .premium-title {
        font-weight: 800;
        letter-spacing: -1.5px;
        background: linear-gradient(90deg, #f0c04a, #ffffff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 20px;
        font-size: 3rem;
    }
    
    /* Sidebar Focus */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid rgba(255,255,255,0.05);
    }
    
    /* Custom Button Style */
    div.stButton > button {
        border-radius: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Tabs Customization */
    .stTabs [data-baseweb="tab-list"] {
        gap: 30px;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 700;
        height: 50px;
        background-color: transparent;
        border: none;
        color: #888;
    }
    .stTabs [aria-selected="true"] {
        color: #f0c04a !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- [Security: Premium Login] -----------------
access_pwd = os.getenv("APP_PASSWORD", "quant1234")
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; color: #f0c04a; font-size: 3.5em;'>💎</h1>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center; color: white;'>Quant Terminal Login</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666;'>Encrypted Node Access Point</p>", unsafe_allow_html=True)
        pwd_input = st.text_input("", type="password", placeholder="Enter authorization key...", label_visibility="collapsed")
        if st.button("AUTHENTICATE SYSTEM", use_container_width=True):
            if pwd_input == access_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("Access Denied: Invalid Authorization Key.")
    st.stop()

# ----------------- [Sidebar: Modular Settings] -----------------
with st.sidebar:
    st.markdown("<h2 style='color: #f0c04a; margin-bottom: 20px;'>🛠️ Configuration</h2>", unsafe_allow_html=True)
    
    with st.expander("🌐 CORE ASSETS", expanded=True):
        exch = st.selectbox("Market Exchange", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"])
        sym = st.text_input("Asset Pair", value="BTC/USDT")
        eng = st.selectbox("Strategy Engine", ["Vectorbt", "Backtrader"], index=0)
    
    with st.expander("📅 TIME & DATA", expanded=True):
        tf = st.selectbox("Interval", ["2h", "1h", "4h", "15m", "5m", "1m"], index=0)
        c1, c2 = st.columns(2)
        sd = c1.date_input("Start", datetime.date(2022, 1, 1))
        ed = c2.date_input("End", datetime.date.today())
        lim = st.number_input("Max Batch Size", 100, 5000, 1000)
    
    with st.expander("⚡ OPTIMIZATION", expanded=True):
        trials = st.slider("Total Trials", 10, 2000, 100)
        workers = st.radio("CPU Workers", [2, 4, 8], index=1, horizontal=True)

    st.markdown("<br>", unsafe_allow_html=True)
    btn_start = st.button("🚀 UNLEASH OPTIMIZER", type="primary", use_container_width=True)
    
    if st.button("🔄 Reload Logic Default", use_container_width=True):
        st.session_state["trigger_code_refresh"] = True
        st.rerun()

# ----------------- [Main Interface] -----------------
st.markdown("<h1 class='premium-title'>QUANTUM ENGINE TERMINAL</h1>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📊 LIVE MONITORING", "📝 STRATEGY ENGINE", "📜 DATA ARCHIVE"])

# Dashboard metrics placeholder helper
def draw_card(label, value, color="#f0c04a"):
    st.markdown(f"""
    <div class="metric-card">
        <p style="color: #666; font-size: 0.85em; font-weight: 700; margin: 0;">{label}</p>
        <h2 style="color: {color}; margin: 10px 0; font-size: 1.8em;">{value}</h2>
    </div>
    """, unsafe_allow_html=True)

with tab1:
    # Top Row Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1: p_m1 = st.empty()
    with c2: p_m2 = st.empty()
    with c3: p_m3 = st.empty()
    with c4: p_m4 = st.empty()
    
    # Init cards
    with p_m1: draw_card("BEST YIELD", "0.00%")
    with p_m2: draw_card("EST. WIN RATE", "0.00%")
    with p_m3: draw_card("MAX DRAWDOWN", "0.00%")
    with p_m4: draw_card("PROCESSED", "0 / 0")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Progress Section
    st.markdown("### 📡 Real-time Telemetry")
    gauge_slot = st.empty()
    status_slot = st.empty()
    
    with st.expander("ℹ️ Simulation Log Stream", expanded=False):
        log_slot = st.empty()

with tab2:
    st.markdown("### 📝 Algorithmic Logic (Python)")
    if "strategy_code" not in st.session_state or st.session_state.get("trigger_code_refresh"):
        # Logic is injected from external files during task.md flow
        st.session_state["strategy_code"] = "Strategy Loading..." 
        st.session_state["trigger_code_refresh"] = False
    
    sc = st.text_area("Implementation Editor", value=st.session_state["strategy_code"], height=500)
    if sc != st.session_state["strategy_code"]: st.session_state["strategy_code"] = sc

with tab3:
    st.markdown("### 📜 Finalized Strategy Reports")
    os.makedirs("results", exist_ok=True)
    res_files = [f for f in glob.glob("results/*.xlsx")]
    if not res_files:
        st.info("Archive is empty. Completed backtests will appear here.")
    else:
        res_files.sort(key=os.path.getmtime, reverse=True)
        for i, fp in enumerate(res_files[:8]):
            fn = os.path.basename(fp)
            with st.container():
                st.markdown(f"<div style='background: #1c2128; padding: 15px; border-radius: 8px; margin-bottom: 5px; border-left: 4px solid #f0c04a;'>📁 {fn}</div>", unsafe_allow_html=True)
                with open(fp, "rb") as f:
                    st.download_button(label="Download Asset", data=f, file_name=fn, key=f"dl_{i}")

# ----------------- [Logic System] -----------------
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
    with st.spinner("⚡ Fetching Market Data..."):
        data = fetch_candles(exch, sym, tf, sd, ed, lim)
    
    if data is not None and not data.empty:
        dp = get_cache_path(exch, sym, tf, sd, ed)
        sn = f"study_{int(time.time())}"
        header = [run_optuna_worker.s(sn, dp, eng, st.session_state["strategy_code"], trials//workers, sym) for i in range(workers)]
        callback = finalize_optuna_study.s(sn, dp, eng, sym)
        res = chord(header)(callback)
        active_task = {"task_id": res.id, "study_name": sn, "n_trials": trials, "symbol": sym}
        with open(CACHE_FILE, "w") as f: json.dump(active_task, f)
        st.rerun()

if active_task:
    tk = AsyncResult(active_task["task_id"], app=celery_app)
    storage = JournalStorage(JournalRedisStorage("redis://localhost:6379/1"))
    
    while not tk.ready():
        try:
            study = optuna.load_study(study_name=active_task["study_name"], storage=storage)
            compl = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
            best = study.best_value if compl > 0 else 0.0
            
            p_val = min(int(compl / active_task["n_trials"] * 100), 100)
            gauge_slot.progress(p_val, text=f"Exploring Optimization Space: {compl} / {active_task['n_trials']}")
            
            with p_m1: draw_card("BEST YIELD", f"{best:.2f}%", "#00c853" if best > 0 else "#f0c04a")
            with p_m4: draw_card("PROCESSED", f"{compl} / {active_task['n_trials']}")
            status_slot.markdown(f"<p style='text-align: center; color: #888;'>📡 Connected to Cluster... Target identified at <b>{best:.2f}%</b> Profit</p>", unsafe_allow_html=True)
        except: pass
        time.sleep(2)

    final = tk.get()
    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
    if final.get('status') == 'SUCCESS':
        st.balloons()
        with p_m1: draw_card("FINAL YIELD", f"{final['best_value']:.2f}%", "#00c853")
        st.success(f"Final results archived. Peak ROI: {final['best_value']:.2f}%")
        with tab1:
            with open(final['excel_file'], "rb") as f:
                st.download_button("📥 DOWNLOAD QUANT REPORT", f, f"Best_{active_task['symbol']}.xlsx", type="primary")
