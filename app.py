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
from celery.result import AsyncResult

from core.tasks import run_optuna_worker, finalize_optuna_study, celery_app
from celery import chord

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
    engine = st.selectbox("백테스트 엔진", ["Backtrader", "Vectorbt"])
    
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
        t = self.p.matype
        p = self.p.period
        d = self.data
        
        if t == 'SMA': 
            self.lines.ma = bt.indicators.SMA(d, period=p)
        elif t == 'EMA': 
            self.lines.ma = bt.indicators.EMA(d, period=p)
        elif t == 'SMMA (RMA)': 
            self.lines.ma = bt.indicators.SmoothedMovingAverage(d, period=p)
        elif t == 'WMA': 
            self.lines.ma = bt.indicators.WeightedMovingAverage(d, period=p)
        elif t == 'VWMA':
            vol = self.data._owner.volume if hasattr(self.data, '_owner') else self.data.volume
            cv = d * vol
            self.lines.ma = bt.indicators.SMA(cv, period=p) / bt.indicators.SMA(vol, period=p)
        else: 
            self.lines.ma = bt.indicators.SMA(d, period=p)

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
        
    def next(self):
        mavg = self.mavg[0]
        fark = mavg * self.p.percent * 0.01
        
        longStop = mavg - fark
        shortStop = mavg + fark
        
        if len(self) == 1 + (self.p.period + self.p.length) or not hasattr(self, 'longStopPrev'):
            self.longStopPrev = longStop
            self.shortStopPrev = shortStop
            self.dir = 1
            
        if mavg > self.longStopPrev:
            longStop = max(longStop, self.longStopPrev)
        if mavg < self.shortStopPrev:
            shortStop = min(shortStop, self.shortStopPrev)
            
        if self.dir == -1 and mavg > self.shortStopPrev:
            self.dir = 1
        elif self.dir == 1 and mavg < self.longStopPrev:
            self.dir = -1
            
        mt = longStop if self.dir == 1 else shortStop
        hott = mt * (200 + self.p.percent) / 200 if mavg > mt else mt * (200 - self.p.percent) / 200
        
        self.lines.hott[0] = hott
        self.longStopPrev = longStop
        self.shortStopPrev = shortStop

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
        mid = self.mid_ma[0]
        std = self.stddev[0] * self.p.dev
        
        lbbdev = max(std, mid * self.p.min_width / 100.0)
        top = mid + lbbdev
        bot = mid - lbbdev
        
        self.lines.mid[0] = mid
        self.lines.top[0] = top
        self.lines.bot[0] = bot

# ==========================================
# [메인 전략] 파인스크립트(Partial Exit) 복제형
# ==========================================
class TestStrategy(bt.Strategy):
    params = (
        ('use_date_range', False),
        ('start_date', datetime.datetime(1900, 1, 1)),
        ('end_date', datetime.datetime(2050, 1, 1)),
        ('entry_type', 'both'),
        ('hl_price', optuna_trial.suggest_categorical('hl_price', ['BB', 'H/L OTT', 'MAX']) if 'optuna_trial' in globals() and optuna_trial else 'H/L OTT'),
        ('open_at_hl', optuna_trial.suggest_categorical('open_at_hl', ['limits', 'close']) if 'optuna_trial' in globals() and optuna_trial else 'limits'),
        ('open_at_ll', optuna_trial.suggest_categorical('open_at_ll', ['limits', 'close']) if 'optuna_trial' in globals() and optuna_trial else 'limits'),
        ('exit_at_hl', optuna_trial.suggest_categorical('exit_at_hl', ['limits', 'close']) if 'optuna_trial' in globals() and optuna_trial else 'close'),
        ('exit_at_ll', optuna_trial.suggest_categorical('exit_at_ll', ['limits', 'close']) if 'optuna_trial' in globals() and optuna_trial else 'limits'),
        ('hl_tp_price', optuna_trial.suggest_categorical('hl_tp_price', ['Fixed', 'ATR', 'both']) if 'optuna_trial' in globals() and optuna_trial else 'ATR'),
        ('hl_sl_price', optuna_trial.suggest_categorical('hl_sl_price', ['Fixed', 'ATR', 'both']) if 'optuna_trial' in globals() and optuna_trial else 'ATR'),
        ('tr_hl', optuna_trial.suggest_categorical('tr_hl', [True, False]) if 'optuna_trial' in globals() and optuna_trial else True),
        ('ll_volatility_filter', optuna_trial.suggest_categorical('ll_volatility_filter', [True, False]) if 'optuna_trial' in globals() and optuna_trial else False),
        ('ma1_length', optuna_trial.suggest_int('ma1_length', 10, 50) if 'optuna_trial' in globals() and optuna_trial else 20),
        ('ll_mult', optuna_trial.suggest_float('ll_mult', 1.0, 3.0) if 'optuna_trial' in globals() and optuna_trial else 1.5),
        ('ma2_type', optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('ma2_length', optuna_trial.suggest_int('ma2_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 3),
        ('bb_ma_type', optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('bb_length', optuna_trial.suggest_int('bb_length', 10, 50) if 'optuna_trial' in globals() and optuna_trial else 20),
        ('bb_dev', optuna_trial.suggest_float('bb_dev', 1.0, 3.0) if 'optuna_trial' in globals() and optuna_trial else 2.0),
        ('bb_min_width', optuna_trial.suggest_float('bb_min_width', 1.0, 5.0) if 'optuna_trial' in globals() and optuna_trial else 3.0),
        ('hott_ma_type', optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('hott_length', optuna_trial.suggest_int('hott_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 2),
        ('hott_percent', optuna_trial.suggest_float('hott_percent', 0.1, 2.0) if 'optuna_trial' in globals() and optuna_trial else 0.6),
        ('hott_h_length', optuna_trial.suggest_int('hott_h_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('hott_use_high', optuna_trial.suggest_categorical('hott_use_high', [True, False]) if 'optuna_trial' in globals() and optuna_trial else False),
        ('high_int', optuna_trial.suggest_int('high_int', 0, 1) if 'optuna_trial' in globals() and optuna_trial else 0),
        ('entry_ll_per', optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15) if 'optuna_trial' in globals() and optuna_trial else 0.06),
        ('tp_hl_per', optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_hl_per', optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07) if 'optuna_trial' in globals() and optuna_trial else 0.02),
        ('tp_ll_per', optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_ll_per', optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('atr_length', optuna_trial.suggest_int('atr_length', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('atr_length2', optuna_trial.suggest_int('atr_length2', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('hl_tp_atr_mul', optuna_trial.suggest_float('hl_tp_atr_mul', 1.0, 6.0) if 'optuna_trial' in globals() and optuna_trial else 2.0),
        ('hl_sl_atr_mul', optuna_trial.suggest_float('hl_sl_atr_mul', 1.0, 6.0) if 'optuna_trial' in globals() and optuna_trial else 4.0),
        ('tr_ma_type', optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('tr_ma_length', optuna_trial.suggest_int('tr_ma_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('exchange_decimal', optuna_trial.suggest_int('exchange_decimal', 0, 8) if 'optuna_trial' in globals() and optuna_trial else 3),
        ('installment', optuna_trial.suggest_categorical('installment', [1, 2]) if 'optuna_trial' in globals() and optuna_trial else 1),
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        self.atr_tp = bt.indicators.ATR(self.datas[0], period=self.p.atr_length)
        self.atr_sl = bt.indicators.ATR(self.datas[0], period=self.p.atr_length2)
        vol_src = (self.datahigh - self.datalow) / bt.If(self.dataclose > 0, self.dataclose, 0.000001)
        self.ma1 = bt.indicators.SMA(vol_src, period=self.p.ma1_length)
        self.ma2 = UniversalMA(self.dataclose, period=self.p.ma2_length, matype=self.p.ma2_type)
        self.bb = BBCustom(period=self.p.bb_length, dev=self.p.bb_dev, min_width=self.p.bb_min_width, matype=self.p.bb_ma_type)
        self.hott = HOTTIndicator(period=self.p.hott_h_length, length=self.p.hott_length, percent=self.p.hott_percent, use_high=self.p.hott_use_high, matype=self.p.hott_ma_type)
        self.tr_ma = UniversalMA(self.dataclose, period=self.p.tr_ma_length, matype=self.p.tr_ma_type)
        
        self.inst_qty = 0 # 1분할 수량
        self.pending_orders = []
        self.pending_exits = []

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            if order.isbuy():
                # 진입 성공 시 1분할 수량 계산 (전량 / Installment)
                self.inst_qty = order.executed.size / self.p.installment
            elif order.issell():
                if not self.position:
                    self.inst_qty = 0
            
        self.pending_orders = [o for o in self.pending_orders if o.ref != order.ref]
        self.pending_exits = [o for o in self.pending_exits if o.ref != order.ref]

    def next(self):
        if self.p.use_date_range:
            dt = self.datas[0].datetime.datetime(0)
            if not (self.p.start_date <= dt < self.p.end_date): return
            
        close_p = self.dataclose[0]
        safe_close = max(close_p, 0.000001)
        safe_cap = max(self.broker.getvalue(), 0)
        
        lbbUpper = self.bb.lines.top[0]
        hott_val = self.hott.lines.hott[0]
        if self.p.high_int > 0 and len(self) > self.p.high_int: hott_val = self.hott.lines.hott[-self.p.high_int]
        
        if self.p.hl_price == 'BB': hl_base = lbbUpper
        elif self.p.hl_price == 'H/L OTT': hl_base = hott_val
        elif self.p.hl_price == 'MAX': hl_base = max(hott_val, lbbUpper)
        else: hl_base = min(hott_val, lbbUpper)
        
        hl_plot = hl_base
        ll_cond = self.ma2[0] * (1 - self.ma1[0] * self.p.ll_mult - self.p.entry_ll_per) if self.p.ll_volatility_filter else self.ma2[0] * (1 - self.p.entry_ll_per)
        ll_plot = ll_cond
        
        # 1. 진입 로직 (항상 100% 전량 진입)
        if not self.position and len(self.pending_orders) == 0:
            pow10 = math.pow(10, self.p.exchange_decimal)
            qty_raw = math.floor((safe_cap / safe_close) * pow10) / pow10
            
            if self.p.open_at_hl == 'limits' and close_p <= hl_plot:
                ord = self.buy(exectype=bt.Order.Stop, price=hl_plot, size=qty_raw)
                self.pending_orders.append(ord)
            elif self.p.open_at_hl == 'close' and close_p > hl_plot:
                ord = self.buy(size=qty_raw)
                self.pending_orders.append(ord)
            elif self.p.open_at_ll == 'limits' and close_p >= ll_plot:
                ord = self.buy(exectype=bt.Order.Limit, price=ll_plot, size=qty_raw)
                self.pending_orders.append(ord)
            elif self.p.open_at_ll == 'close' and close_p < ll_plot:
                ord = self.buy(size=qty_raw)
                self.pending_orders.append(ord)

        # 2. 청산 로직 (분할 매도 방식)
        if self.position.size > 0:
            # TP/SL 가격 계산 (최신 진입가 기준)
            last_entry = self.position.price
            
            # HL 계열 익절/손경 (ATR/Fixed 선택)
            tp_hl_f = last_entry * (1 + self.p.tp_hl_per)
            tp_hl_a = last_entry + self.p.hl_tp_atr_mul * self.atr_tp[0]
            tp_hl = tp_hl_f if self.p.hl_tp_price == 'Fixed' else (tp_hl_a if self.p.hl_tp_price == 'ATR' else max(tp_hl_f, tp_hl_a))
            
            sl_hl_f = last_entry * (1 - self.p.sl_hl_per)
            sl_hl_a = last_entry - self.p.hl_sl_atr_mul * self.atr_sl[0]
            sl_hl = sl_hl_f if self.p.hl_sl_price == 'Fixed' else (sl_hl_a if self.p.hl_sl_price == 'ATR' else max(sl_hl_f, sl_hl_a))
            
            # LL 계열 익절/손경 (Fixed 고정)
            tp_ll = last_entry * (1 + self.p.tp_ll_per)
            sl_ll = last_entry * (1 - self.p.sl_ll_per)
            
            # 청산 신호 체크
            is_tp = False
            is_sl = False
            
            # 현재 포지션이 HL인지 LL인지 구분하여 TP/SL 체크 (단순화를 위해 합집합 가능)
            if close_p >= tp_hl or close_p >= tp_ll: is_tp = True
            if close_p <= sl_hl or close_p <= sl_ll: is_sl = True
            
            # 분할 매도 실행 (신호 발생 봉마다 1/Installment 만큼 매도)
            if is_tp or is_sl:
                # 이번 봉에서 팔 수량 (전체의 1/N 또는 남은 전량)
                sell_qty = min(self.inst_qty, self.position.size)
                if sell_qty > 0:
                    self.sell(size=sell_qty)
            
            # TR MA 추적 청산 (On 시 전량 청산)
            if self.p.tr_hl and close_p < self.tr_ma[0] and self.dataclose[-1] >= self.tr_ma[-1]:
                self.close()

# ==========================================
# 하단 실행부
# ==========================================
cerebro = bt.Cerebro()
class PandasDataFeed(bt.feeds.PandasData):
    params = (('datetime', None), ('open', 'Open'), ('high', 'High'), ('low', 'Low'), ('close', 'Close'), ('volume', 'Volume'), ('openinterest', -1))
if 'data' in globals():
    data_feed = PandasDataFeed(dataname=data)
    cerebro.adddata(data_feed)
    cerebro.addstrategy(TestStrategy)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0008)
    cerebro.broker.set_slippage_fixed(0.3)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    total_prof = final_value - initial_value
    ret_pct = round((total_prof / initial_value) * 100, 2)
    win_rate = 0.0
    mdd = 0.0
    total_tr = 0
    if results:
        strat = results[0]
        try:
            trade_info = strat.analyzers.trades.get_analysis()
            dd_info = strat.analyzers.drawdown.get_analysis()
            total_tr = trade_info.total.total if 'total' in trade_info else 0
            if total_tr > 0 and 'won' in trade_info:
                won_tr = trade_info.won.total
                win_rate = round((won_tr / total_tr) * 100, 2)
            if 'max' in dd_info and 'drawdown' in dd_info.max:
                mdd = round(dd_info.max.drawdown, 2)
        except Exception: pass
    metrics = {
        "Total Return (%)": ret_pct,
        "Total Profit": round(total_prof, 2),
        "Win Rate (%)": win_rate,
        "MDD (%)": mdd,
        "Total Trades": total_tr
    }
"""
    else:
        default_code = """# Vectorbt 엔진용 전략 스크립트 템플릿입니다.
# 'data' 변수와 'optuna_trial' 변수가 런타임에 주입됩니다.
import vectorbt as vbt
import pandas as pd

close = data['Close']

# Optuna 파라미터 최적화 (fast는 5~20 튜닝, slow는 30~100 사이 튜닝)
if 'optuna_trial' in globals() and optuna_trial:
    fast_period = optuna_trial.suggest_int('fast', 5, 20)
    slow_period = optuna_trial.suggest_int('slow', 30, 100)
else:
    fast_period = 10
    slow_period = 50

# 이동평균 계산 및 신호 생성
fast_ma = vbt.MA.run(close, fast_period, short_name='fast')
slow_ma = vbt.MA.run(close, slow_period, short_name='slow')

entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

# 포트폴리오 백테스트
portfolio = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10000)

# 결과 메트릭 추출
metrics = {
    "Total Return (%)": round(portfolio.total_return() * 100, 2) if hasattr(portfolio, 'total_return') else 0,
    "Win Rate (%)": round(portfolio.win_rate() * 100, 2) if hasattr(portfolio, 'win_rate') else 0,
    "Max Drawdown (%)": round(portfolio.max_drawdown() * 100, 2) if hasattr(portfolio, 'max_drawdown') else 0,
    "Total Trades": portfolio.trades.count() if hasattr(portfolio, 'trades') else 0
}
"""
    
    strategy_code = st.text_area("파이썬 코드를 작성하세요", value=default_code, height=450)

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
            st.warning("🔄 접속 종료 또는 새로고침 되기 전 수신된 백그라운드 최적화 작업을 자동 복구(Re-attach)하여 추적합니다.")
        else:
            os.remove(CACHE_FILE)
    except Exception:
        pass

# 실행 및 결과 처리 플로우 (비동기 방식)
if start_btn and not active_task:
    st.subheader("🔄 최적화 실행 진행 현황")
    
    # 1. 분산 처리를 위한 설정 (4코어 활용)
    study_name = f"study_{int(time.time())}"
    trials_per_worker = n_trials // 4
    rem = n_trials % 4
    
    # 2. Header: 4개의 병렬 워커 생성
    header = []
    for i in range(4):
        header.append(run_optuna_worker.s(
            study_name=study_name,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=str(start_date),
            end_date=str(end_date),
            limit=limit,
            engine=engine,
            code_str=strategy_code,
            n_trials=trials_per_worker + (rem if i == 3 else 0)
        ))
    
    # 3. Callback: 모든 워커 완료 후 통합 리포트 생성
    callback = finalize_optuna_study.s(
        study_name=study_name,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        start_date=str(start_date),
        end_date=str(end_date),
        limit=limit,
        engine=engine
    )
    
    # 4. Chord 실행
    result = chord(header)(callback)
    
    # 프로세스 캐시 저장 (result.id는 callback 태스크의 ID임)
    active_task = {
        "task_id": result.id, 
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
    
    st.info(f"🚀 4개 코어 분산 백테스트 실행 중... (Callback ID: {task.id})")
    
    status_placeholder = st.empty()
    gauge_placeholder = st.empty()
    
    study_name = active_task["study_name"]
    redis_url = "redis://localhost:6379/1"
    storage = JournalStorage(JournalRedisStorage(redis_url))
    
    # 폴링 루프 시작 시간
    loop_start_time = time.time()
    MAX_WAIT_TIME = 3600 # 1시간 타임아웃
    
    with st.spinner("Celery 큐 대기 및 최적화 진행 중... (새로고침 하셔도 됩니다)"):
        while True:
            # 1. 태스크 상태 체크 (무한 로딩 방지 핵심)
            if task.ready():
                break
                
            if task.status in ['FAILURE', 'REVOKED']:
                st.error(f"⚠️ 백그라운드 작업이 비정상 종료되었습니다. (상태: {task.status})")
                break

            # 2. 루프 타임아웃 체크
            if time.time() - loop_start_time > MAX_WAIT_TIME:
                st.error("⚠️ 최적화 작업 허용 시간(1시간)을 초과하여 추적을 중단합니다.")
                break
            
            # 3. Redis Optuna 진행률 폴링 (최적화 버전)
            try:
                study = optuna.load_study(study_name=study_name, storage=storage)
                # study.trials 전체를 가져오지 않고 필터링된 개수만 확인하여 속도 향상
                completed_trials = study.get_trials(states=[optuna.trial.TrialState.COMPLETE])
                completed = len(completed_trials)
                
                best_val = 0.0
                if completed > 0:
                    try:
                        best_val = study.best_value
                    except (ValueError, Exception):
                        pass
                
                prog = min(int(completed / n_trials_meta * 100), 100)
                gauge_placeholder.progress(prog, text=f"완료 횟수: {completed} / {n_trials_meta}")
                status_placeholder.markdown(f"### 🔥 현재 찾아낸 최고 수익률: **{best_val:.2f}%**")
                
            except Exception as e:
                # study가 아직 생성되지 않았거나 Redis 연결 지연 시 예외 처리
                status_placeholder.markdown("⏳ Optuna 데이터베이스 초기화 및 동기화 대기 중...")
            
            time.sleep(3.0)
            
    # 최종 결과 반환
    try:
        final_res = task.get()
    except Exception as e:
        final_res = {"status": "FAILED", "reason": f"Celery 작업 중단 및 예외 발생: {str(e)}"}
    
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
        st.error(f"작업 실패 또는 에러 발생: {final_res}")
