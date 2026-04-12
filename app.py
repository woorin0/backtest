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

# 고가독성 페이지 설정 (라이트 테마 지향)
st.set_page_config(
    page_title="퀀트 최적화 터미널",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed" # 모바일을 위해 사이드바 기본 닫힘
)

# ----------------- [CSS: 고가독성 라이트 테마 & 모바일 최적화] -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;700;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Pretendard', sans-serif;
        background-color: #ffffff !important;
        color: #121212 !important;
    }
    
    /* 카드 스타일 (밝고 뚜렷한 구분) */
    .metric-card {
        background-color: #f8f9fa;
        border: 2px solid #eeeeee;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    /* 제목 스타일 */
    .main-title {
        font-weight: 900;
        letter-spacing: -1.5px;
        color: #007aff;
        margin-bottom: 20px;
        font-size: 2.2rem;
        text-align: center;
    }
    
    /* 사이드바 스타일 */
    section[data-testid="stSidebar"] {
        background-color: #f2f2f7;
        border-right: 1px solid #e5e5ea;
    }
    
    /* 버튼 스타일 (확인 용이) */
    div.stButton > button {
        border-radius: 10px;
        font-weight: 700;
        height: 3em;
        font-size: 1.1em;
    }
    
    /* 에디터 텍스트 가독성 */
    .stTextArea textarea {
        font-size: 14px !important;
        font-family: 'Consolas', monospace !important;
        background-color: #fafafa !important;
        color: #1a1a1a !important;
    }

    /* 모바일 대응: 가로 여백 조정 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- [보안: 한국어 로그인 화면] -----------------
access_pwd = os.getenv("APP_PASSWORD", "jumbonuts")
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>🔐 시스템 접속</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        pwd_input = st.text_input("접속 비밀번호를 입력해 주세요 (Password)", type="password")
        if st.button("시스템 인증 시작", use_container_width=True):
            if pwd_input == access_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# ----------------- [사이드바: 한국어 설정 제어판] -----------------
with st.sidebar:
    st.markdown("### 🛠️ 엔진 상세 설정")
    
    with st.expander("🌐 자산 및 엔진 선택", expanded=True):
        exch = st.selectbox("연동 거래소", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"], index=0)
        sym = st.text_input("심볼 (예: BTC/USDT)", value="BTC/USDT")
        eng = st.selectbox("구동 엔진", ["Vectorbt", "Backtrader"], index=0)
    
    with st.expander("📅 데이터 기간 설정", expanded=True):
        tf = st.selectbox("봉 주기 (Interval)", ["1h", "2h", "4h", "15m", "5m", "1m"], index=0)
        sd = st.date_input("시작일", datetime.date(2022, 1, 1))
        ed = st.date_input("종료일", datetime.date.today())
        lim = st.number_input("최대 봉 갯수", 100, 10000, 1000)
    
    with st.expander("⚡ 최적화 전략 제어", expanded=True):
        # 사용자 요청: 최대 시도수 10,000회 상향
        trials = st.number_input("총 탐색 시도 횟수", 10, 10000, 100, step=100)
        workers = st.radio("병렬 워커 수", [2, 4, 8], index=1)

    st.markdown("---")
    btn_start = st.button("🚀 최적화 엔진 가동", type="primary", use_container_width=True)
    if st.button("🔄 엔진 초기화 (기본값)", use_container_width=True):
        st.session_state["trigger_code_refresh"] = True
        st.rerun()

# ----------------- [메인 화면: 수직 통합 레이아웃 (탭 제거)] -----------------
st.markdown("<h1 class='main-title'>📈 퀀트 백테스트 최적화 터미널</h1>", unsafe_allow_html=True)

# 섹션 1: 통합 지표 대시보드
st.markdown("### 📊 실시간 최고 성과 지표")
c1, c2 = st.columns(2) # 모바일을 위해 2열씩 배치
with c1: p_m1 = st.empty()
with c2: p_m2 = st.empty()
c3, c4 = st.columns(2)
with c3: p_m3 = st.empty()
with c4: p_m4 = st.empty()

def draw_metric(label, value, color="#121212"):
    st.markdown(f"""
    <div class="metric-card">
        <p style="color: #666; font-size: 0.9em; font-weight: 700; margin: 0;">{label}</p>
        <h2 style="color: {color}; margin: 5px 0; font-size: 1.8em;">{value}</h2>
    </div>
    """, unsafe_allow_html=True)

# 초기화 상태 카드
p_m1.markdown(draw_metric("최고 수익률", "0.00%"), unsafe_allow_html=True)
p_m2.markdown(draw_metric("추정 승률", "0.00%"), unsafe_allow_html=True)
p_m3.markdown(draw_metric("최대 낙폭(MDD)", "0.00%"), unsafe_allow_html=True)
p_m4.markdown(draw_metric("진행률", "0 / 0"), unsafe_allow_html=True)

st.divider()

# 섹션 2: 진행 현황 모니터링
st.markdown("### 🛰️ 엔진 구동 현황")
gauge_slot = st.empty()
status_slot = st.empty()

with st.expander("📝 실시간 실행 로그 보기", expanded=False):
    log_slot = st.empty()

st.divider()

# 섹션 3: 전략 코드 에디터 (수직 배치)
st.markdown("### 📝 전략 알고리즘 (Python)")
if "strategy_code" not in st.session_state or st.session_state.get("trigger_code_refresh"):
    from core.templates import VECTORBT_STRATEGY, BACKTRADER_STRATEGY
    st.session_state["strategy_code"] = VECTORBT_STRATEGY if eng == "Vectorbt" else BACKTRADER_STRATEGY
    st.session_state["trigger_code_refresh"] = False

sc = st.text_area("로직 에디터 (여기서 코드를 수정할 수 있습니다)", value=st.session_state["strategy_code"], height=400)
if sc != st.session_state["strategy_code"]: 
    st.session_state["strategy_code"] = sc

st.divider()

# 섹션 4: 리포트 보관소
st.markdown("### 📜 최종 리포트 보관소")
os.makedirs("results", exist_ok=True)
res_files = [f for f in glob.glob("results/*.xlsx")]
if not res_files:
    st.info("현재 보관된 리포트가 없습니다. 최적화를 실행하면 결과가 여기 표시됩니다.")
else:
    res_files.sort(key=os.path.getmtime, reverse=True)
    for i, fp in enumerate(res_files[:5]):
        fn = os.path.basename(fp)
        with st.container():
            st.markdown(f"<div style='background: #f1f3f5; padding: 12px; border-radius: 8px; margin-bottom: 5px;'>📁 {fn}</div>", unsafe_allow_html=True)
            with open(fp, "rb") as f:
                st.download_button(label=f"📥 {fn[:20]}... 다운로드", data=f, file_name=fn, key=f"dl_k_{i}", use_container_width=True)

# ----------------- [백그라운드 로직: Celery & Optuna] -----------------
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
    with st.spinner("📦 시장 데이터를 가져오는 중..."):
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
            gauge_slot.progress(p_val, text=f"전체 {active_task['n_trials']}회 중 {compl}회 탐색 완료")
            
            p_m1.markdown(draw_metric("최고 수익률", f"{best:.2f}%", "#34C759" if best > 0 else "#121212"), unsafe_allow_html=True)
            p_m4.markdown(draw_metric("진행률", f"{compl} / {active_task['n_trials']}"), unsafe_allow_html=True)
            status_slot.markdown(f"<p style='text-align: center; color: #666;'>📡 AI가 최적의 파라미터를 찾는 중... 현재 최고 수익률: <b>{best:.2f}%</b></p>", unsafe_allow_html=True)
        except: pass
        time.sleep(2)

    final = tk.get()
    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
    if final.get('status') == 'SUCCESS':
        st.balloons()
        p_m1.markdown(draw_metric("최종 최고 수익률", f"{final['best_value']:.2f}%", "#34C759"), unsafe_allow_html=True)
        st.success(f"✅ 최적화가 완료되었습니다. 최종 결과: {final['best_value']:.2f}%")
        with open(final['excel_file'], "rb") as f:
            st.download_button("📥 최종 최적 성과 리포트 다운로드", f, f"Best_{active_task['symbol']}.xlsx", type="primary", use_container_width=True)
