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
from core.notifier import send_discord_error, send_discord_alert

# 환경 변수 로드
load_dotenv()

# 고가독성 페이지 설정
st.set_page_config(
    page_title="퀀트 최적화 터미널",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ----------------- [CSS: 디자인 최적화] -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;700;900&display=swap');
    html, body, [class*="css"] {
        font-family: 'Pretendard', sans-serif;
        background-color: #ffffff !important;
        color: #121212 !important;
    }
    .metric-card {
        background-color: #f8f9fa;
        border: 2px solid #eeeeee;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .main-title {
        font-weight: 900;
        letter-spacing: -1.5px;
        color: #007aff;
        margin-bottom: 20px;
        font-size: 2.2rem;
        text-align: center;
    }
    div.stButton > button {
        border-radius: 10px;
        font-weight: 700;
        height: 3.5em;
    }
    .stProgress > div > div > div > div {
        background-color: #007aff;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- [보안 로그인] -----------------
access_pwd = os.getenv("APP_PASSWORD", "jumbonuts")
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>🔐 시스템 접속</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        pwd_input = st.text_input("접속 비밀번호를 입력해 주세요", type="password")
        if st.button("시스템 인증 시작", use_container_width=True):
            if pwd_input == access_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# ----------------- [사이드바 설정] -----------------
with st.sidebar:
    st.markdown("### 🛠️ 엔진 상세 설정")
    with st.expander("🌐 자산 및 엔진", expanded=True):
        exch = st.selectbox("거래소", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"], index=0)
        sym = st.text_input("심볼", value="BTC/USDT")
        eng = st.selectbox("엔진", ["Vectorbt", "Backtrader"], index=0)
    with st.expander("📅 기간 및 주기", expanded=True):
        tf = st.selectbox("주기", ["1h", "2h", "4h", "15m", "5m", "1m"], index=0)
        sd = st.date_input("시작일", datetime.date(2022, 1, 1))
        ed = st.date_input("종료일", datetime.date.today())
        lim = st.number_input("최대 봉 갯수", 100, 10000, 1000)
    with st.expander("⚡ 최적화 설정", expanded=True):
        trials = st.number_input("총 탐색 시도 횟수", 10, 10000, 100, step=100)
        workers = st.radio("병렬 워커(코어)", [2, 4, 8], index=1)

    st.markdown("---")
    btn_start = st.button("🚀 최적화 가동", type="primary", use_container_width=True)
    if st.button("🔄 엔진 초기화", use_container_width=True):
        st.session_state["trigger_code_refresh"] = True
        st.rerun()

# ----------------- [메인 화면 UI] -----------------
st.markdown("<h1 class='main-title'>📈 퀀트 백테스트 최적화 Terminal</h1>", unsafe_allow_html=True)

# 섹션 1: 실시간 성과 지표
st.markdown("### 📊 실시간 최고 성과")
c1, c2 = st.columns(2)
with c1: p_m1 = st.empty()
with c2: p_m2 = st.empty()
c3, c4 = st.columns(2)
with c3: p_m3 = st.empty()
with c4: p_m4 = st.empty()

def draw_metric(label, value, color="#121212"):
    st.markdown(f"<div class='metric-card'><p style='color: #666; font-size: 0.9em; font-weight: 700; margin: 0;'>{label}</p><h2 style='color: {color}; margin: 5px 0; font-size: 1.8em;'>{value}</h2></div>", unsafe_allow_html=True)

p_m1.markdown(draw_metric("최고 수익률", "0.00%"), unsafe_allow_html=True)
p_m2.markdown(draw_metric("추정 승률", "0.00%"), unsafe_allow_html=True)
p_m3.markdown(draw_metric("최대 낙폭", "0.00%"), unsafe_allow_html=True)
p_m4.markdown(draw_metric("탐색 진행", f"0 / {trials}"), unsafe_allow_html=True)

st.divider()

# 섹션 2: 진행 모니터링
st.markdown("### 🛰️ 엔진 모니터링")
gauge_slot = st.empty()
status_slot = st.empty()
# 🚨 최적화 중단 버튼 스페이스
stop_btn_slot = st.empty()

st.divider()

# 섹션 3: 전략 에디터
st.markdown("### 📝 전략 알고리즘")
if "strategy_code" not in st.session_state or st.session_state.get("trigger_code_refresh"):
    from core.templates import VECTORBT_STRATEGY, BACKTRADER_STRATEGY
    st.session_state["strategy_code"] = VECTORBT_STRATEGY if eng == "Vectorbt" else BACKTRADER_STRATEGY
    st.session_state["trigger_code_refresh"] = False

sc = st.text_area("코드 편집기", value=st.session_state["strategy_code"], height=350)
if sc != st.session_state["strategy_code"]: st.session_state["strategy_code"] = sc

st.divider()

# 섹션 4: 리포트 보관소
st.markdown("### 📜 최근 리포트 (최신 3개)")
os.makedirs("results", exist_ok=True)
res_files = glob.glob("results/*.xlsx")
res_files.sort(key=os.path.getmtime, reverse=True)

for i, fp in enumerate(res_files[:3]):
    fn = os.path.basename(fp)
    with st.container():
        st.markdown(f"<div style='background: #f1f3f5; padding: 10px; border-radius: 8px; margin-bottom: 5px;'>📁 {fn}</div>", unsafe_allow_html=True)
        with open(fp, "rb") as f:
            st.download_button(label=f"📥 다운로드", data=f, file_name=fn, key=f"dl_sys_{i}", use_container_width=True)

if len(res_files) > 3:
    with st.expander("더 많은 리포트 보기"):
        for i, fp in enumerate(res_files[3:15]):
            fn = os.path.basename(fp)
            with open(fp, "rb") as f:
                st.download_button(label=f"📄 {fn}", data=f, file_name=fn, key=f"dl_extra_{i}")

# ----------------- [백그라운드 로직 및 중단 제어] -----------------
CACHE_FILE = ".active_task.json"
active_task = None
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: meta = json.load(f)
        task_check = AsyncResult(meta["task_id"], app=celery_app)
        if not task_check.ready(): active_task = meta
        else: os.remove(CACHE_FILE)
    except: pass

# 🚀 최적화 시작 로직
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
        active_task = {"task_id": res.id, "study_name": sn, "n_trials": trials, "symbol": sym, "start_time": time.time()}
        with open(CACHE_FILE, "w") as f: json.dump(active_task, f)
        st.rerun()
    else:
        # 데이터 수집 실패 시 디스코드 알림
        send_discord_error(f"데이터 수집 실패: {sym}", pair=sym, engine=eng)
        st.error("데이터를 가져오는 데 실패했습니다. 심볼이나 네트워크 상태를 확인해 주세요.")

# 🛰️ 모니터링 및 중단 로직
if active_task:
    tk = AsyncResult(active_task["task_id"], app=celery_app)
    
    # [제어] 최적화 중단 버튼
    if stop_btn_slot.button("🛑 최적화 중단 (STOP)", type="secondary", use_container_width=True):
        celery_app.control.revoke(active_task["task_id"], terminate=True)
        if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
        st.warning("⚠️ 최적화가 사용자에 의해 중지되었습니다.")
        time.sleep(2)
        st.rerun()

    storage = JournalStorage(JournalRedisStorage("redis://localhost:6379/1"))
    while not tk.ready():
        # 오류 발생 시 디스코드 알림 체크
        if tk.status == 'FAILURE':
            send_discord_error("백그라운드 최적화 작업 중 치명적인 오류 발생", pair=active_task['symbol'], engine="CentralTask")
            break

        try:
            study = optuna.load_study(study_name=active_task["study_name"], storage=storage)
            compl = len(study.get_trials(states=[optuna.trial.TrialState.COMPLETE]))
            best = study.best_value if compl > 0 else 0.0
            
            p_val = min(int(compl / active_task["n_trials"] * 100), 100)
            gauge_slot.progress(p_val, text=f"{compl} / {active_task['n_trials']} 회 탐색 중")
            
            p_m1.markdown(draw_metric("최고 수익률", f"{best:.2f}%", "#34C759" if best > 0 else "#121212"), unsafe_allow_html=True)
            p_m4.markdown(draw_metric("탐색 진행", f"{compl} / {active_task['n_trials']}"), unsafe_allow_html=True)
            
            if compl == 0:
                elapsed = int(time.time() - (active_task.get("start_time") or time.time()))
                if elapsed > 180:
                    status_slot.warning(f"⚠️ {elapsed}초 경과: 아직 결과가 없습니다. 워커 상태를 확인해 주세요.")
                else:
                    status_slot.markdown(f"<p style='text-align: center; color: #ff9800;'>⏳ <b>엔진 시동 중:</b> 분석 대기 중... {elapsed}초 경과</p>", unsafe_allow_html=True)
            else:
                status_slot.markdown(f"<p style='text-align: center; color: #007aff;'>📡 최고 {best:.2f}% 수익률 탐지 완료... 계속 탐색 중</p>", unsafe_allow_html=True)
        except: pass
        time.sleep(3)

    # 최종 결과 처리
    try:
        final = tk.get(timeout=5)
        if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
        if final.get('status') == 'SUCCESS':
            st.balloons()
            p_m1.markdown(draw_metric("최종 결과", f"{final['best_value']:.2f}%", "#34C759"), unsafe_allow_html=True)
            st.success(f"✅ 최적화 완료! 최고의 수익률: {final['best_value']:.2f}%")
            with open(final['excel_file'], "rb") as f:
                st.download_button("🚀 [중요] 최적 성과 리포트(Excel) 받기", f, f"Best_{active_task['symbol']}.xlsx", type="primary", use_container_width=True)
    except Exception as e:
        if "timeout" not in str(e).lower():
            send_discord_error(f"최종 집계 중 오류: {str(e)}", pair=active_task.get('symbol', 'Unknown'))
            st.error("결과 집계 중 오류가 발생했습니다. 디소코드를 확인해 주세요.")
