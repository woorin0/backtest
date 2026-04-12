import streamlit as st
import os
import datetime
import math
import json
from dotenv import load_dotenv

import time
import optuna
from optuna.storages import JournalStorage
try:
    from optuna.storages import JournalRedisStorage
except ImportError:
    from optuna_integration.storages import JournalRedisStorage
from celery.result import AsyncResult, GroupResult
from celery import chord
from core.tasks import run_optuna_worker, finalize_optuna_study, celery_app
from core.notifier import send_discord_error

# 환경 변수 로드
load_dotenv()

st.set_page_config(page_title="Quant Backtest Dashboard", layout="wide")

# ----------------- 보안: 기본 암호 로그인 기능 -----------------
access_pwd = os.getenv("APP_PASSWORD", "quant1234")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("🔒 잠긴 대시보드 (보안 접속)")
    st.info("외부 접속자가 악의적인 코드를 실행할 수 없도록 보호되어 있습니다.")
    pwd_input = st.text_input("접속 비밀번호를 입력하세요 (기본값: quant1234)", type="password")
    
    if st.button("로그인", use_container_width=True):
        if pwd_input == access_pwd:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("비밀번호가 일치하지 않습니다.")
    st.stop()
# -----------------------------------------------------------------

with st.sidebar:
    st.header("📥 과거 백테스트 결과")
    st.info("이전에 완료된 백테스트 엑셀을 다운로드할 수 있습니다.")
    
    if not os.path.exists("results"):
        os.makedirs("results", exist_ok=True)
        
    import glob
    excel_files = glob.glob("results/*.xlsx")
    if not excel_files:
        st.write("아직 저장된 결과 파일이 없습니다.")
    else:
        excel_files.sort(key=os.path.getmtime, reverse=True)
        for i, fpath in enumerate(excel_files[:15]): # 최신 15개까지만 노출
            fname = os.path.basename(fpath)
            disp_name = fname.replace("Best_Backtest_", "").replace(".xlsx", "")
            with open(fpath, "rb") as ext_file:
                st.download_button(
                    label=f"📊 {disp_name}",
                    data=ext_file,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_history_{i}"
                )

# CSS 커스텀 스타일
st.markdown("""
<style>
div.stButton > button:first-child {
    background-color: #4CAF50;
    color: white;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 웹 기반 퀀트 최적화 대시보드 (비동기 처리)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ 설정 항목")
    exchange = st.selectbox("거래소", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"])
    symbol = st.text_input("종목 쌍", value="BTC/USDT")
    
    # [원복] 백트레이더를 기본 엔진으로 설정 (index=0)
    engine = st.selectbox("백테스트 엔진", ["Backtrader", "Vectorbt"], index=0, key="engine_select")
    
    # 세션 상태 초기화 및 관리
    if "strategy_code" not in st.session_state:
        st.session_state["strategy_code"] = ""
        st.session_state["current_engine"] = "Backtrader"
        st.session_state["trigger_code_refresh"] = True

    if engine != st.session_state["current_engine"]:
        st.session_state["current_engine"] = engine
        st.session_state["trigger_code_refresh"] = True
    
    st.markdown("---")
    st.subheader("📅 타임프레임 및 최적화 설정")
    timeframe = st.text_input("타임프레임 (예: 1d, 4h, 1h, 15m, 5m, 1m)", value="2h")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("시작일", value=datetime.date(2017, 1, 1))
    with col_d2:
        end_date = st.date_input("종료일", value=datetime.date.today())
        
    limit = st.number_input("1회 요청 최대 갯수", min_value=100, max_value=5000, value=1000, step=100)
    n_trials = st.number_input("Optuna 최적화 반복 탐색 횟수", min_value=10, max_value=10000, value=100, step=50)
    
    start_btn = st.button("🚀 백테스트 최적화 시작", use_container_width=True)

with col2:
    st.subheader("💻 전략 코드 입력")
    
    if engine == "Backtrader":
        default_code = """import backtrader as bt
import math
import datetime

# ==========================================
# [커스텀 지표 MAs] 여러 MA 지원 래퍼
# ==========================================
class UniversalMA(bt.Indicator):
    lines = ('ma',)
    params = (('period', 20), ('matype', 'SMA'))
    def __init__(self):
        t = self.p.matype; p = self.p.period; d = self.data
        if t == 'SMA': self.lines.ma = bt.indicators.SMA(d, period=p)
        elif t == 'EMA': self.lines.ma = bt.indicators.EMA(d, period=p)
        elif t == 'SMMA (RMA)': self.lines.ma = bt.indicators.SmoothedMovingAverage(d, period=p)
        elif t == 'WMA': self.lines.ma = bt.indicators.WeightedMovingAverage(d, period=p)
        elif t == 'VWMA':
            vol = self.data._owner.volume if hasattr(self.data, '_owner') else self.data.volume
            cv = d * vol
            self.lines.ma = bt.indicators.SMA(cv, period=p) / bt.indicators.SMA(vol, period=p)
        else: self.lines.ma = bt.indicators.SMA(d, period=p)

# ==========================================
# [커스텀 지표 1] HOTT (Optimized Trend Tracker)
# ==========================================
class HOTTIndicator(bt.Indicator):
    lines = ('hott',)
    params = (('period', 100), ('length', 2), ('percent', 0.6), ('use_high', False), ('matype', 'EMA'))
    def __init__(self):
        src_data = self.data.high if self.p.use_high else self.data.close
        self.highest_val = bt.indicators.Highest(src_data, period=self.p.period)
        self.mavg = UniversalMA(self.highest_val, period=self.p.length, matype=self.p.matype)
        self.addminperiod(self.p.period + self.p.length)
        self.longStopPrev = None; self.shortStopPrev = None; self.dir = 1
    def next(self):
        mavg = self.mavg[0]; fark = mavg * self.p.percent * 0.01
        longStop = mavg - fark; shortStop = mavg + fark
        if self.longStopPrev is None:
            self.longStopPrev = longStop; self.shortStopPrev = shortStop
        if mavg > self.longStopPrev: longStop = max(longStop, self.longStopPrev)
        if mavg < self.shortStopPrev: shortStop = min(shortStop, self.shortStopPrev)
        if self.dir == -1 and mavg > self.shortStopPrev: self.dir = 1
        elif self.dir == 1 and mavg < self.longStopPrev: self.dir = -1
        mt = longStop if self.dir == 1 else shortStop
        hott = mt * (200 + self.p.percent) / 200 if mavg > mt else mt * (200 - self.p.percent) / 200
        self.lines.hott[0] = hott; self.longStopPrev = longStop; self.shortStopPrev = shortStop

# ==========================================
# [커스텀 지표 2] BB Width/Diff 결합형 밴드
# ==========================================
class BBCustom(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('dev', 2.0), ('min_width', 3.0), ('matype', 'EMA'))
    def __init__(self):
        self.mid_ma = UniversalMA(self.data.close, period=self.p.period, matype=self.p.matype)
        self.stddev = bt.indicators.StdDev(self.data.close, period=self.p.period)
    def next(self):
        mid = self.mid_ma[0]; std = self.stddev[0] * self.p.dev
        lbbdev = max(std, mid * self.p.min_width / 100.0)
        self.lines.mid[0] = mid; self.lines.top[0] = mid + lbbdev; self.lines.bot[0] = mid - lbbdev

# ==========================================
# [메인 전략] 파인스크립트(Dual Long) 복제형
# ==========================================
class TestStrategy(bt.Strategy):
    params = (
        ('hl_price', 'H/L OTT'), ('tp_hl_per', 0.015), ('sl_hl_per', 0.02),
        ('ma1_length', 20), ('ll_mult', 1.5), ('entry_ll_per', 0.06),
        ('atr_length', 10), ('hl_tp_atr_mul', 2.0), ('hl_sl_atr_mul', 4.0),
        ('installment', 1), ('tr_hl', True),
    )
    def __init__(self):
        self.dataclose = self.datas[0].close; self.datahigh = self.datas[0].high; self.datalow = self.datas[0].low
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_length)
        safe_close = bt.If(self.dataclose > 0, self.dataclose, 0.000001)
        self.ma1 = bt.indicators.SMA((self.datahigh - self.datalow) / safe_close, period=self.p.ma1_length)
        self.ma2 = bt.indicators.EMA(self.dataclose, period=3)
        self.bb = BBCustom(period=20, dev=2.0)
        self.hott = HOTTIndicator(period=100, length=2, percent=0.6)
        self.tr_ma = bt.indicators.SMA(self.dataclose, period=100)
        self.entry_id = None; self.tp_order = None; self.sl_order = None; self.is_first_filled = False

    def issue_exit_orders(self, base_price, size):
        if self.entry_id == 'HL':
            tp_p = max(base_price * (1 + self.p.tp_hl_per), base_price + self.p.hl_tp_atr_mul * self.atr[0])
            sl_p = max(base_price * (1 - self.p.sl_hl_per), base_price - self.p.hl_sl_atr_mul * self.atr[0])
        else: # LL
            tp_p = base_price * (1 + 0.015); sl_p = base_price * (1 - 0.02)
        self.tp_order = self.sell(exectype=bt.Order.Limit, price=tp_p, size=size)
        self.sl_order = self.sell(exectype=bt.Order.Stop, price=sl_p, size=size, oco=self.tp_order)

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_id = order.info.get('id')
                size = order.executed.size / self.p.installment
                self.issue_exit_orders(order.executed.price, size)
            elif order.issell():
                self.tp_order = None; self.sl_order = None
                if self.position.size > 0: self.is_first_filled = True
                else: self.is_first_filled = False

    def next(self):
        if not self.position:
            hl_plot = self.hott.hott[0] if self.p.hl_price == 'H/L OTT' else self.bb.top[0]
            ll_plot = self.ma2[0] * (1 - self.ma1[0] * self.p.ll_mult - self.p.entry_ll_per)
            if self.datahigh[0] > hl_plot:
                o = self.buy(exectype=bt.Order.Stop, price=hl_plot); o.info['id'] = 'HL'
            elif self.datalow[0] < ll_plot:
                o = self.buy(exectype=bt.Order.Limit, price=ll_plot); o.info['id'] = 'LL'
        else:
            if self.is_first_filled and not self.tp_order:
                self.issue_exit_orders(self.position.price, self.position.size)
                self.is_first_filled = False
            if self.p.tr_hl and self.dataclose[0] < self.tr_ma[0]:
                self.close()

cerebro = bt.Cerebro()
data_feed = bt.feeds.PandasData(dataname=data)
cerebro.adddata(data_feed)
cerebro.addstrategy(TestStrategy)
cerebro.broker.setcash(10000.0)
    else:
        default_code = """# [100.0% Parity] Vectorbt 초정밀 가속 전략 (Final Version)
import vectorbt as vbt
import pandas as pd
import numpy as np
from numba import njit

# 1. 데이터 및 파라미터 로드
c_np, h_np, l_np = data['Close'].values, data['High'].values, data['Low'].values

if 'optuna_trial' in globals() and optuna_trial:
    # 🚨 [100.0% Parity] HL/LL 독립 모드 설정
    hl_price_type = optuna_trial.suggest_categorical('hl_price', ['BB', 'H/L OTT', 'MAX'])
    
    # BB 및 HOTT 상세 설정
    bb_ma_type, bb_len = optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('bb_length', 10, 50)
    bb_dev_in, bb_min_w = optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1), optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1)
    hott_ma_type, hott_len = optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('hott_length', 1, 10)
    hott_per, hott_h_len = optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1), optuna_trial.suggest_int('hott_h_length', 50, 200)
    hott_h_src, h_int = optuna_trial.suggest_categorical('hott_h_src', ['High', 'close']), optuna_trial.suggest_int('high_int', 0, 5)
    
    # 🚨 진입/청산 모드 분리 (HL vs LL)
    o_m_hl, o_m_ll = optuna_trial.suggest_categorical('open_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('open_at_ll', ['limits', 'close'])
    e_m_hl, e_m_ll = optuna_trial.suggest_categorical('exit_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('exit_at_ll', ['limits', 'close'])
    
    # 전략 핵심 수치
    tp_hl_type, sl_hl_type = optuna_trial.suggest_categorical('hl_tp_price', ['Fixed', 'ATR', 'both']), optuna_trial.suggest_categorical('hl_sl_price', ['Fixed', 'ATR', 'both'])
    ma2_type, ma2_len, ma1_len = optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA']), optuna_trial.suggest_int('ma2_length', 1, 10), optuna_trial.suggest_int('ma1_length', 10, 50)
    tr_ma_type, tr_ma_len = optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('tr_ma_length', 50, 200)
    atr_len, atr_len2 = optuna_trial.suggest_int('atr_length', 7, 20), optuna_trial.suggest_int('atr_length2', 7, 20)
    ll_mult, ll_vol_filter = optuna_trial.suggest_float('ll_mult', 1.0, 3.0, step=0.1), optuna_trial.suggest_categorical('ll_volatility_filter', [True, False])
    en_ll_per = optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.0001)
    
    # 익절/손절 상세 (HL/LL 분리)
    tp_hl_per, sl_hl_per = optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.0001), optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.0001)
    tp_ll_per, sl_ll_per = optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.0001), optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.0001)
    
    inst, tr_hl, slippage = optuna_trial.suggest_categorical('installment', [1, 2]), optuna_trial.suggest_categorical('tr_hl', [True, False]), 0.0001
else:
    # 기본값 설정
    hl_price_type, bb_ma_type, bb_len, bb_dev_in, bb_min_w = 'H/L OTT', 'EMA', 20, 2.0, 3.0
    hott_ma_type, hott_len, hott_per, hott_h_len, hott_h_src, h_int = 'EMA', 2, 0.6, 100, 'close', 0
    o_m_hl, o_m_ll, e_m_hl, e_m_ll = 'limits', 'limits', 'close', 'limits'
    tp_hl_type, sl_hl_type = 'both', 'both'
    ma2_type, ma2_len, ma1_len, tr_ma_type, tr_ma_len, atr_len, atr_len2 = 'EMA', 3, 20, 'EMA', 100, 10, 10
    ll_mult, ll_vol_filter, en_ll_per = 1.5, False, 0.06
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per = 0.015, 0.02, 0.015, 0.015
    inst, tr_hl, slippage = 1, True, 0.0001

# 2. 지표 계산 (Digital Twin)
def calc_ma(s, l, t): return s.ewm(span=l, adjust=True).mean() if t == 'EMA' else s.rolling(l).mean()

bb_mid = calc_ma(data['Close'], bb_len, bb_ma_type)
bb_std = data['Close'].rolling(bb_len).std()
bb_dev = np.maximum(bb_std * bb_dev_in, bb_mid * bb_min_w / 100.0)
bb_u = (bb_mid + bb_dev).values
h_src = data['High'] if hott_h_src == 'High' else data['Close']
mavg_h_np = h_src.rolling(hott_h_len).max().ewm(span=hott_len).mean().values
atr_tp, atr_sl = vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len).atr.values, vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len2).atr.values
ma1 = ((data['High'] - data['Low']) / data['Close'].replace(0, 0.0001)).rolling(ma1_len).mean().values
ma2, tr_ma = calc_ma(data['Close'], ma2_len, ma2_type).values, calc_ma(data['Close'], tr_ma_len, tr_ma_type).values

@njit
def calc_hott_nb(mavg_np, percent):
    n = len(mavg_np); hott = np.zeros(n); lsp, ssp, dv = 0.0, 0.0, 1
    for i in range(1, n):
        ma = mavg_np[i]; fk = ma * percent * 0.01
        ls, ss = ma - fk, ma + fk
        if i == 1: lsp, ssp = ls, ss
        if ma > lsp: lsp = max(ls, lsp)
        if ma < ssp: ssp = min(ss, ssp)
        if dv == -1 and ma > ssp: dv = 1
        elif dv == 1 and ma < lsp: dv = -1
        mt = lsp if dv == 1 else ssp
        hott[i] = mt * (200 + percent) / 200 if ma > mt else mt * (200 - percent) / 200
    return hott

hott_v = calc_hott_nb(mavg_h_np, hott_per)
hl_p_raw, ll_p_raw = (hott_v if hl_price_type == 'H/L OTT' else (bb_u if hl_price_type == 'BB' else np.maximum(hott_v, bb_u))), (ma2 * (1 - ma1 * ll_mult - en_ll_per) if ll_vol_filter else ma2 * (1 - en_ll_per))

# 3. 초정밀 시뮬레이터 (The Real 100.0% Parity)
@njit
def sim_final_nb(h, l, c, hlp_raw, llp_raw, atp, ats, trm, inst_num, use_tr, o_m_h, o_m_l, e_m_h, e_m_l, tp_t, sl_t, h_i, tph, slh, tpl, sll):
    n = len(c); en, ex, pr, sz = np.zeros(n, dtype=np.bool_), np.zeros(n, dtype=np.bool_), np.zeros(n), np.zeros(n)
    pos, ep, etp, esl, pf, bfe, eid = False, 0.0, 0.0, 0.0, 0, -1, 0
    for i in range(1 + h_i, n):
        hlp, llp = hlp_raw[i-1-h_i], llp_raw[i-1]
        if not pos:
            t_en_h = (h[i] > hlp) if o_m_h == 'limits' else (c[i] > hlp)
            if t_en_h and hlp > 0:
                en[i]=True; eid=1; pos=True; pr[i]=hlp if o_m_h=='limits' else c[i]; ep=pr[i]; etp=atp[i]; esl=ats[i]; sz[i]=1.0
            else:
                t_en_l = (l[i] < llp) if o_m_l == 'limits' else (c[i] < llp)
                if t_en_l and llp > 0:
                    en[i]=True; eid=2; pos=True; pr[i]=llp if o_m_l=='limits' else c[i]; ep=pr[i]; etp=atp[i]; esl=ats[i]; sz[i]=1.0
        else:
            if eid == 1: # HL Case
                tf, ta = ep*(1+tph), ep + 2.0*etp
                tpp = tf if tp_t=='Fixed' else (ta if tp_t=='ATR' else max(tf, ta))
                sf, sa = ep*(1-slh), ep - 4.0*esl
                slp = sf if sl_t=='Fixed' else (sa if sl_t=='ATR' else max(sf, sa))
                # 🚨 [해결] TR 청산 - 오직 HL(eid == 1)일 때만 작동
                if use_tr and c[i] < trm[i] and c[i-1] >= trm[i-1]:
                    ex[i], pr[i], sz[i], pos = True, c[i], -1.0, False; continue
                t_ex = (h[i]>=tpp or l[i]<=slp) if e_m_h=='limits' else (c[i]>=tpp or c[i]<=slp)
                e_act = e_m_h
            else: # LL Case
                tpp, slp = ep*(1+tpl), ep*(1-sll)
                # LL은 TR 청산 무시 (가이드 적용)
                t_ex = (h[i]>=tpp or l[i]<=slp) if e_m_l=='limits' else (c[i]>=tpp or c[i]<=slp)
                e_act = e_m_l
            
            if t_ex:
                xp = (tpp if h[i]>=tpp else slp) if e_act=='limits' else c[i]
                if inst_num == 1:
                    ex[i], pr[i], sz[i], pos = True, xp, -1.0, False
                elif pf == 0:
                    ex[i], pr[i], sz[i], pf, bfe = True, xp, -0.5, 1, i
                elif i > bfe:
                    ex[i], pr[i], sz[i], pos = True, xp, -1.0, False
    return en, ex, pr, sz

en, ex, pr, sz = sim_final_nb(h_np, l_np, c_np, hl_p_raw, ll_p_raw, atr_tp, atr_sl, tr_ma, inst, tr_hl, o_m_hl, o_m_ll, e_m_hl, e_m_ll, tp_hl_type, sl_hl_type, h_int, tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per)
portfolio = vbt.Portfolio.from_signals(data['Close'], en, ex, price=pr, size=sz, size_type='percent', init_cash=10000, fees=0.0008, slippage=slippage)
metrics = {"Total Return (%)": round(portfolio.total_return()*100, 2), "Win Rate (%)": round(portfolio.win_rate()*100, 2), "MDD (%)": round(portfolio.max_drawdown()*100, 2), "Total Trades": int(portfolio.trades.count())}
    
    if st.session_state.get("trigger_code_refresh") or st.session_state["strategy_code"] == "":
        st.session_state["strategy_code"] = default_code
        st.session_state["trigger_code_refresh"] = False
        
    strategy_code = st.text_area("파이썬 코드를 작성하세요", value=st.session_state["strategy_code"], height=450, key="code_editor")
    
    # 에디터 내용 실시간 세션 반영
    if strategy_code != st.session_state["strategy_code"]:
        st.session_state["strategy_code"] = strategy_code

st.markdown("---")

CACHE_FILE = ".active_task.json"
active_task = None

# 캐시 파일 감지 및 로드 (새로고침 복구용)
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f:
            meta = json.load(f)
        task_check = AsyncResult(meta["task_id"], app=celery_app)
        if not task_check.ready():
            active_task = meta
            # 깜빡임 방지를 위해 Recovery 모드 플래그만 설정
            st.session_state["recovery_active"] = True
        else:
            os.remove(CACHE_FILE)
    except Exception:
        pass

# 실행 및 결과 처리 플로우 (비동기 방식)
if start_btn and not active_task:
    st.subheader("🔄 최적화 실행 진행 현황")
    
    # 1. 데이터 먼저 수집 (메인 워커에서 한 번만 수행하여 캐시 생성)
    from core.data_fetcher import fetch_candles, get_cache_path
    progress_bar = st.progress(0, text="데이터 수집 준비 중...")
    data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, progress_bar=progress_bar)
    
    if data is None or data.empty:
        st.error("데이터 수집에 실패했습니다. 거래소 설정이나 기간을 확인해주세요.")
    else:
        # 데이터 캐시 경로 확보
        data_path = get_cache_path(exchange, symbol, timeframe, start_date, end_date)
        
        # 2. 분산 처리를 위한 설정 (4코어 선점)
        study_name = f"study_{int(time.time())}"
        trials_per_worker = n_trials // 4
        rem = n_trials % 4
        
        # 3. Header: 4개의 병렬 워커 생성 (데이터 경로 전달)
        header = []
        for i in range(4):
            header.append(run_optuna_worker.s(
                study_name=study_name,
                data_path=data_path, # 수집된 캐시 경로 전달
                engine=engine,
                code_str=strategy_code,
                n_trials=trials_per_worker + (rem if i == 3 else 0),
                symbol=symbol
            ))
        
        # 4. Callback: 모든 워커 완료 후 통합 리포트 생성
        callback = finalize_optuna_study.s(
            study_name=study_name,
            data_path=data_path,
            engine=engine,
            symbol=symbol
        )
        
        # 5. Chord 실행
        result = chord(header)(callback)
        worker_ids = [h.id for h in header]
        
        # 프로세스 캐시 저장
        active_task = {
            "task_id": result.id, 
            "worker_ids": worker_ids,
            "study_name": study_name,
            "n_trials": n_trials,
            "exchange": exchange,
            "symbol": symbol,
            "engine": engine
        }
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(active_task, f)
    except Exception:
        pass

if active_task:
    task = AsyncResult(active_task["task_id"], app=celery_app)
    n_trials_meta = active_task["n_trials"]
    ex_meta = active_task.get("exchange", "Unknown")
    sym_meta = active_task.get("symbol", "BTC").replace('/', '-')
    engine_meta = active_task.get("engine", "Engine")
    
    # 1. UI 고정 컨테이너 (깜빡임 방지)
    status_box = st.container()
    with status_box:
        if st.session_state.get("recovery_active"):
            st.warning("🔄 이전 세션에서 진행 중이던 최적화 작업을 복구하여 추적 중입니다.")
        
        st.info(f"🚀 4개 코어 병렬 분산 백테스트 실행 중... (ID: {task.id})")
        
        # 중단 버튼 (위치 고정)
        if st.button("🛑 백테스트 즉시 중단 (Force Stop)", use_container_width=True):
            celery_app.control.revoke(active_task["task_id"], terminate=True)
            worker_ids = active_task.get("worker_ids", [])
            for wid in worker_ids:
                celery_app.control.revoke(wid, terminate=True)
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
            send_discord_error(f"사용자가 대시보드에서 작업을 강제 중단했습니다.", pair=sym_meta, engine=engine_meta)
            st.warning("🛑 작업이 중단되었습니다. 메인 화면으로 돌아갑니다.")
            time.sleep(1)
            st.rerun()

        st.divider()
        status_placeholder = st.empty()
        gauge_placeholder = st.empty()
    
    study_name = active_task["study_name"]
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    
    # 루프 시작 전 타임리밋 설정 (1시간 -> 24시간 연장)
    loop_start_at = time.time()
    LIMIT_24H = 86400 # 24시간
    
    # 최적화 진행률 추적 루프 (st.spinner 제거하여 깜빡임 방지)
    while True:
        if task.ready():
            break
            
        # 1. 태스크 상태 모니터링
        if task.status in ['FAILURE', 'REVOKED']:
            st.error(f"⚠️ 백그라운드 작업이 비정상 종료되었습니다. (상태: {task.status})")
            break

        # 2. 24시간 타임리밋 체크
        if time.time() - loop_start_at > LIMIT_24H:
            status_placeholder.error("🚨 최적화 시간이 24시간을 경과하여 시스템 보호를 위해 추적을 중단합니다.")
            break
            
        # 3. Redis 상태 감시 및 UI 업데이트
        try:
            study = optuna.load_study(study_name=study_name, storage=storage)
            all_trials = study.get_trials(states=[optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.PRUNED])
            processed = len(all_trials)
            
            best_val = 0.0
            if processed > 0:
                try:
                    best_val = study.best_value
                except:
                    pass
            
            prog = min(int(processed / n_trials_meta * 100), 100)
            gauge_placeholder.progress(prog, text=f"진행 상황: {processed} / {n_trials_meta} 탐색 중...")
            status_placeholder.markdown(f"### 🔥 현재 찾아낸 최고 수익률: **{best_val:.2f}%**")
            
        except Exception:
            status_placeholder.info("⏳ 워커가 Redis DB와 연결 중이거나 초기화 대기 중입니다...")
        
        time.sleep(3.0)
            
    # 최종 결과 반환 및 에러 리포팅 강화
    try:
        final_res = task.get(timeout=10) # Safety timeout
    except Exception as e:
        final_res = {"status": "FAILED", "reason": f"Celery 결과 수신 실패 (타임아웃 또는 예외): {str(e)}"}
    
    # 작업이 끝났으므로 캐시 삭제
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except Exception:
            pass
            
    if isinstance(final_res, dict) and final_res.get('status') == 'SUCCESS':
        gauge_placeholder.progress(100, text="최적화 완전 종료")
        st.success(f"🎉 완료되었습니다! 최종 최고 수익률: **{final_res.get('best_value'):.2f}%**")
        st.info("🔔 디스코드 웹훅으로 최적화 완료 알림이 전송되었습니다.")
        
        # 엑셀 다운로드
        excel_path = final_res.get('excel_file')
        if excel_path and os.path.exists(excel_path):
            with open(excel_path, "rb") as f:
                st.download_button(
                    label="📥 최고 성과 추출 엑셀 다운로드 (.xlsx)",
                    data=f,
                    file_name=f"Best_Backtest_{ex_meta}_{sym_meta}_{engine_meta}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    else:
        gauge_placeholder.empty()
        err_msg = f"작업 실패 또는 에러 발생: {final_res}"
        st.error(err_msg)
        # 디스코드 에러 알림 (이미 tasks.py에서 보냈을 수 있지만, 여기서도 한 번 더 확인)
        send_discord_error(str(final_res), pair=sym_meta, engine=engine_meta)
