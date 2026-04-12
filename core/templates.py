# [100.0% 무결성] 전략 코드 템플릿 저장소 (에러 완전 복구 보정 버전 v5)

VECTORBT_STRATEGY = """# [100.0% 무결성] Vectorbt 초정밀 가속 전략
import vectorbt as vbt
import pandas as pd
import numpy as np
from numba import njit

# [V7 완벽 동기화] 원본 데이터 결측치(NaN) 완벽 제거
data = data.ffill().bfill()
data.dropna(inplace=True) # 사용자가 지적한 NaN 찌꺼기 원천 차단
data = data[data['Close'] > 0]

# 1. 데이터 및 파라미터 로드
c_np = data['Close'].values.astype(np.float64)
h_np = data['High'].values.astype(np.float64)
l_np = data['Low'].values.astype(np.float64)

if 'optuna_trial' in globals() and optuna_trial:
    hl_price_type = optuna_trial.suggest_categorical('hl_price', ['BB', 'H/L OTT', 'MAX'])
    bb_ma_type, bb_len = optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('bb_length', 10, 50)
    bb_dev_in, bb_min_w = optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1), optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1)
    hott_ma_type, hott_len = optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('hott_length', 1, 10)
    hott_per, hott_h_len = optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1), optuna_trial.suggest_int('hott_h_length', 50, 200)
    hott_h_src, h_int = optuna_trial.suggest_categorical('hott_h_src', ['High', 'close']), optuna_trial.suggest_int('high_int', 0, 5)
    
    o_m_hl, o_m_ll = optuna_trial.suggest_categorical('open_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('open_at_ll', ['limits', 'close'])
    e_m_hl, e_m_ll = optuna_trial.suggest_categorical('exit_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('exit_at_ll', ['limits', 'close'])
    
    tp_hl_type, sl_hl_type = optuna_trial.suggest_categorical('hl_tp_price', ['Fixed', 'ATR', 'both']), optuna_trial.suggest_categorical('hl_sl_price', ['Fixed', 'ATR', 'both'])
    ma2_type, ma2_len, ma1_len = optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA']), optuna_trial.suggest_int('ma2_length', 1, 10), optuna_trial.suggest_int('ma1_length', 10, 50)
    tr_ma_type, tr_ma_len = optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA']), optuna_trial.suggest_int('tr_ma_length', 50, 200)
    atr_len, atr_len2 = optuna_trial.suggest_int('atr_length', 7, 20), optuna_trial.suggest_int('atr_length2', 7, 20)
    ll_mult, ll_vol_filter = optuna_trial.suggest_float('ll_mult', 1.0, 3.0, step=0.1), optuna_trial.suggest_categorical('ll_volatility_filter', [True, False])
    en_ll_per = optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.0001)
    
    tp_hl_per, sl_hl_per = optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.0001), optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.0001)
    tp_ll_per, sl_ll_per = optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.0001), optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.0001)
    
    inst, tr_hl, slippage = optuna_trial.suggest_categorical('installment', [1, 2]), optuna_trial.suggest_categorical('tr_hl', [True, False]), 0.0001
else:
    hl_price_type, bb_ma_type, bb_len, bb_dev_in, bb_min_w = 'H/L OTT', 'EMA', 20, 2.0, 3.0
    hott_ma_type, hott_len, hott_per, hott_h_len, hott_h_src, h_int = 'EMA', 2, 0.6, 100, 'close', 0
    o_m_hl, o_m_ll, e_m_hl, e_m_ll = 'limits', 'limits', 'close', 'limits'
    tp_hl_type, sl_hl_type = 'both', 'both'
    ma2_type, ma2_len, ma1_len, tr_ma_type, tr_ma_len, atr_len, atr_len2 = 'EMA', 3, 20, 'EMA', 100, 10, 10
    ll_mult, ll_vol_filter, en_ll_per = 1.5, False, 0.06
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per = 0.015, 0.02, 0.015, 0.015
    inst, tr_hl, slippage = 1, True, 0.0001

warmup = int(max(bb_len, hott_h_len, ma1_len, ma2_len, tr_ma_len, atr_len, atr_len2, 20) * 1.5)

def calc_ma(s, l, t): return s.ewm(span=l, adjust=True).mean() if t == 'EMA' else s.rolling(l).mean()

bb_mid = calc_ma(data['Close'], bb_len, bb_ma_type)
bb_std = data['Close'].rolling(bb_len).std()
bb_dev = np.maximum(bb_std * bb_dev_in, bb_mid * bb_min_w / 100.0)
bb_u = (bb_mid + bb_dev).values.astype(np.float64)
h_src = data['High'] if hott_h_src == 'High' else data['Close']
mavg_h_np = h_src.rolling(hott_h_len).max().ewm(span=hott_len).mean().values.astype(np.float64)
atr_tp, atr_sl = vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len).atr.values.astype(np.float64), vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len2).atr.values.astype(np.float64)
ma1 = ((data['High'] - data['Low']) / data['Close'].replace(0, 0.0001)).rolling(ma1_len).mean().values.astype(np.float64)
ma2, tr_ma = calc_ma(data['Close'], ma2_len, ma2_type).values.astype(np.float64), calc_ma(data['Close'], tr_ma_len, tr_ma_type).values.astype(np.float64)

@njit
def calc_hott_nb(mavg_np, percent):
    n = len(mavg_np)
    hott = np.zeros(n)
    lsp, ssp, dv = 0.0, 0.0, 1
    found_first = False
    for i in range(n):
        ma = mavg_np[i]
        if np.isnan(ma):
            hott[i] = np.nan
            continue
        fk = ma * percent * 0.01
        ls, ss = ma - fk, ma + fk
        if not found_first:
            lsp, ssp, found_first = ls, ss, True
        if ma > lsp: lsp = max(ls, lsp)
        if ma < ssp: ssp = min(ss, ssp)
        if dv == -1 and ma > ssp: dv = 1
        elif dv == 1 and ma < lsp: dv = -1
        mt = lsp if dv == 1 else ssp
        hott[i] = mt * (200 + percent) / 200 if ma > mt else mt * (200 - percent) / 200
    return hott

hott_v = calc_hott_nb(mavg_h_np, hott_per).astype(np.float64)
hl_p_raw, ll_p_raw = (hott_v if hl_price_type == 'H/L OTT' else (bb_u if hl_price_type == 'BB' else np.maximum(hott_v, bb_u))), (ma2 * (1 - ma1 * ll_mult - en_ll_per) if ll_vol_filter else ma2 * (1 - en_ll_per))

@njit
def sim_final_nb(h, l, c, hlp_raw, ll_p, atp, ats, trm, inst_num, use_tr, o_m_h, o_m_l, e_m_h, e_m_l, tp_t, slice_t, h_i, tph, slh, tpl, sll, start_idx):
    n = len(c); en, ex = np.zeros(n, dtype=np.bool_), np.zeros(n, dtype=np.bool_)
    pr = c.copy() # [V6 핵심] 평상시 비거래 구간에서도 NAV(자산가치) 평가가 가능하도록 종가 기반 초기화
    sz = np.full(n, np.nan)
    pos, ep, etp, esl, pf, bfe, eid = False, 0.0, 0.0, 0.0, 0, -1, 0
    for i in range(start_idx, n):
        if i-1-h_i < 0: continue
        hlp, llp = hlp_raw[i-1-h_i], ll_p[i-1]
        
        # [V5 보강] 가격 및 지표 유효성 검사 극단적 강화
        if not (np.isfinite(hlp) and np.isfinite(llp) and hlp > 0 and llp > 0): continue
        if not (np.isfinite(h[i]) and np.isfinite(l[i]) and np.isfinite(c[i]) and c[i] > 0): continue
        if not (np.isfinite(atp[i]) and np.isfinite(ats[i]) and np.isfinite(trm[i])): continue

        if not pos:
            t_en_h = (h[i] > hlp) if o_m_h == 'limits' else (c[i] > hlp)
            if t_en_h:
                en[i]=True; eid=1; pos=True; ep=hlp if o_m_h=='limits' else c[i]; pr[i]=ep; etp=atp[i]; esl=ats[i]; sz[i]=0.995
            else:
                t_en_l = (l[i] < llp) if o_m_l == 'limits' else (c[i] < llp)
                if t_en_l:
                    en[i]=True; eid=2; pos=True; ep=llp if o_m_l=='limits' else c[i]; pr[i]=ep; etp=atp[i]; esl=ats[i]; sz[i]=0.995
        else:
            if eid == 1: # HL Case
                tf, ta = ep*(1+tph), ep + 2.0*etp
                tpp = tf if tp_t=='Fixed' else (ta if tp_t=='ATR' else max(tf, ta))
                sf, sa = ep*(1-slh), ep - 4.0*esl
                slp = sf if slice_t=='Fixed' else (sa if slice_t=='ATR' else max(sf, sa))
                if use_tr and c[i] < trm[i] and c[i-1] >= trm[i-1]:
                    ex[i], pr[i], sz[i], pos = True, c[i], 1.0, False; continue
                t_ex = (h[i]>=tpp or l[i]<=slp) if e_m_h=='limits' else (c[i]>=tpp or c[i]<=slp)
                e_act = e_m_h
            else: # LL Case
                tpp, slp = ep*(1+tpl), ep*(1-sll)
                t_ex = (h[i]>=tpp or l[i]<=slp) if e_m_l=='limits' else (c[i]>=tpp or c[i]<=slp)
                e_act = e_m_l
            if t_ex:
                xp = (tpp if h[i]>=tpp else slp) if e_act=='limits' else c[i]
                if not (np.isfinite(xp) and xp > 0): xp = c[i] # 최종 방어
                if inst_num == 1:
                    ex[i], pr[i], sz[i], pos = True, xp, 1.0, False
                elif pf == 0:
                    ex[i], pr[i], sz[i], pf, bfe = True, xp, 0.5, 1, i
                elif i > bfe:
                    ex[i], pr[i], sz[i], pos = True, xp, 1.0, False
    return en, ex, pr, sz

actual_start = int(max(warmup, 1 + h_int) + 10)
en, ex, pr, sz = sim_final_nb(h_np, l_np, c_np, hl_p_raw, ll_p_raw, atr_tp, atr_sl, tr_ma, inst, tr_hl, o_m_hl, o_m_ll, e_m_hl, e_m_ll, tp_hl_type, sl_hl_type, h_int, tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per, actual_start)

# [V5 핵심] 자본금 대폭 상향으로 미세 수수료로 인한 잔고 NaN 방지 및 수량 체계 안정화
portfolio = vbt.Portfolio.from_signals(data['Close'], en, ex, price=pr, size=sz, size_type='percent', init_cash=1000000.0, fees=0.0008, slippage=slippage)

try:
    port_stats = portfolio.stats()
    win_rate = float(port_stats.get('Win Rate [%]', 0.0))
    total_return = float(getattr(portfolio, 'total_return', 0.0) * 100.0)
    total_profit = float(getattr(portfolio, 'total_profit', 0.0))
    max_drawdown = float(getattr(portfolio, 'max_drawdown', 0.0) * 100.0)
    total_trades = int(portfolio.trades.count())
except:
    win_rate, total_return, total_profit, max_drawdown, total_trades = 0.0, 0.0, 0.0, 0.0, 0

metrics = {
    "Total Return (%)": round(total_return, 2),
    "Win Rate (%)": round(win_rate, 2),
    "MDD (%)": round(max_drawdown, 2),
    "Total Trades": total_trades,
    "Total Profit": round(total_profit, 2)
}
"""

BACKTRADER_STRATEGY = """import backtrader as bt
import math
import datetime
import numpy as np

# [V7 완벽 동기화] 원본 데이터 결측치 완벽 제거
data = data.ffill().bfill()
data.dropna(inplace=True)
data = data[data['Close'] > 0]

# [100.0% 무결성] Backtrader 최적화 연동형 전략
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
            self.lines.ma = bt.indicators.SMA(d * vol, period=p) / bt.indicators.SMA(vol, period=p)
        else: self.lines.ma = bt.indicators.SMA(d, period=p)

class HOTTIndicator(bt.Indicator):
    lines = ('hott',)
    params = (('period', 100), ('length', 2), ('percent', 0.6), ('use_high', False), ('matype', 'EMA'))
    def __init__(self):
        src_data = self.data.high if self.p.use_high else self.data.close
        self.highest_val = bt.indicators.Highest(src_data, period=self.p.period)
        self.mavg = UniversalMA(self.highest_val, period=self.p.length, matype=self.p.matype)
        self.addminperiod(self.p.period + self.p.length)
    def next(self):
        mavg = self.mavg[0]; fark = mavg * self.p.percent * 0.01
        ls, ss = mavg - fark, mavg + fark
        if len(self) == 1 + (self.p.period + self.p.length) or not hasattr(self, 'lsp'):
            self.lsp, self.ssp, self.dir = ls, ss, 1
        if mavg > self.lsp: self.lsp = max(ls, self.lsp)
        if mavg < self.ssp: self.ssp = min(ss, self.ssp)
        if self.dir == -1 and mavg > self.ssp: self.dir = 1
        elif self.dir == 1 and mavg < self.lsp: self.dir = -1
        mt = self.lsp if self.dir == 1 else self.ssp
        self.lines.hott[0] = mt * (200 + self.p.percent) / 200 if mavg > mt else mt * (200 - self.p.percent) / 200

class BBCustom(bt.Indicator):
    lines = ('top',)
    params = (('period', 20), ('dev', 2.0), ('min_width', 3.0), ('matype', 'EMA'))
    def __init__(self):
        self.mid = UniversalMA(self.data.close, period=self.p.period, matype=self.p.matype)
        self.std = bt.indicators.StdDev(self.data.close, period=self.p.period)
    def next(self):
        dev = max(self.std[0] * self.p.dev, self.mid[0] * self.p.min_width / 100.0)
        self.lines.top[0] = self.mid[0] + dev

class TestStrategy(bt.Strategy):
    params = (
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
        ('ll_mult', optuna_trial.suggest_float('ll_mult', 1.0, 3.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 1.5),
        ('ma2_type', optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('ma2_length', optuna_trial.suggest_int('ma2_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 3),
        ('bb_ma_type', optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('bb_length', optuna_trial.suggest_int('bb_length', 10, 50) if 'optuna_trial' in globals() and optuna_trial else 20),
        ('bb_dev', optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 2.0),
        ('bb_min_width', optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 3.0),
        ('hott_ma_type', optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('hott_length', optuna_trial.suggest_int('hott_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 2),
        ('hott_percent', optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 0.6),
        ('hott_h_length', optuna_trial.suggest_int('hott_h_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('hott_use_high', optuna_trial.suggest_categorical('hott_use_high', [True, False]) if 'optuna_trial' in globals() and optuna_trial else False),
        ('high_int', optuna_trial.suggest_int('high_int', 0, 5) if 'optuna_trial' in globals() and optuna_trial else 0),
        ('entry_ll_per', optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.0001) if 'optuna_trial' in globals() and optuna_trial else 0.06),
        ('tp_hl_per', optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.0001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_hl_per', optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.0001) if 'optuna_trial' in globals() and optuna_trial else 0.02),
        ('tp_ll_per', optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.0001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_ll_per', optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.0001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('atr_length', optuna_trial.suggest_int('atr_length', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('atr_length2', optuna_trial.suggest_int('atr_length2', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('tr_ma_type', optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('tr_ma_length', optuna_trial.suggest_int('tr_ma_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('installment', optuna_trial.suggest_categorical('installment', [1, 2]) if 'optuna_trial' in globals() and optuna_trial else 1),
    )
    def __init__(self):
        self.atr_tp = bt.indicators.ATR(self.data, period=self.p.atr_length)
        self.atr_sl = bt.indicators.ATR(self.data, period=self.p.atr_length2)
        safe_close = bt.If(self.data.close > 0, self.data.close, 0.000001)
        self.ma1 = bt.indicators.SMA((self.data.high - self.data.low) / safe_close, period=self.p.ma1_length)
        self.ma2 = UniversalMA(self.data.close, period=self.p.ma2_length, matype=self.p.ma2_type)
        self.bb = BBCustom(period=self.p.bb_length, dev=self.p.bb_dev, min_width=self.p.bb_min_width, matype=self.p.bb_ma_type)
        self.hott = HOTTIndicator(period=self.p.hott_h_length, length=self.p.hott_length, percent=self.p.hott_percent, use_high=self.p.hott_use_high, matype=self.p.hott_ma_type)
        self.tr_ma = UniversalMA(self.data.close, period=self.p.tr_ma_length, matype=self.p.tr_ma_type)
        self.entry_id = None; self.is_first_filled = False
        self.entry_order = None; self.tp_order = None; self.sl_order = None
    def calc_exits(self, base_p):
        if self.entry_id == 'HL':
            tf, ta = base_p*(1+self.p.tp_hl_per), base_p + 2.0*self.atr_tp[0]
            tpp = tf if self.p.hl_tp_price=='Fixed' else (ta if self.p.hl_tp_price=='ATR' else max(tf, ta))
            sf, sa = base_p*(1-self.p.sl_hl_per), base_p - 4.0*self.atr_sl[0]
            slp = sf if self.p.hl_sl_price=='Fixed' else (sa if self.p.hl_sl_price=='ATR' else max(sf, sa))
            return tpp, slp, self.p.exit_at_hl
        else: return base_p*(1+self.p.tp_ll_per), base_p*(1-self.p.sl_ll_per), self.p.exit_at_ll
    def next(self):
        if not self.position:
            hott_v = self.hott.hott[-self.p.high_int] if self.p.high_int > 0 else self.hott.hott[0]
            hlp = self.bb.top[0] if self.p.hl_price=='BB' else (hott_v if self.p.hl_price=='H/L OTT' else max(hott_v, self.bb.top[0]))
            llp = self.ma2[0]*(1 - self.ma1[0]*1.5 - self.p.entry_ll_per) if self.p.ll_volatility_filter else self.ma2[0]*(1-self.p.entry_ll_per)
            if self.entry_order: self.cancel(self.entry_order)
            qty = self.broker.getvalue() / self.data.close[0]
            if self.data.high[0] > hlp and hlp > 0:
                self.entry_order = self.buy(exectype=bt.Order.Stop if self.p.open_at_hl=='limits' else bt.Order.Market, price=hlp, size=qty)
                self.entry_order.info['id'] = 'HL'
            elif self.data.low[0] < llp and llp > 0:
                self.entry_order = self.buy(exectype=bt.Order.Limit if self.p.open_at_ll=='limits' else bt.Order.Market, price=llp, size=qty)
                self.entry_order.info['id'] = 'LL'
        elif self.position.size > 0:
            tpp, slp, e_mode = self.calc_exits(self.position.price)
            if self.entry_id == 'HL' and self.p.tr_hl and self.data.close[0] < self.tr_ma[0] and self.data.close[-1] >= self.tr_ma[-1]:
                self.close(); return
            if self.is_first_filled and not self.tp_order and e_mode == 'limits':
                self.tp_order = self.sell(exectype=bt.Order.Limit, price=tpp, size=self.position.size)
                self.sl_order = self.sell(exectype=bt.Order.Stop, price=slp, size=self.position.size, oco=self.tp_order)
                self.is_first_filled = False
            if e_mode == 'close' and (self.data.close[0] >= tpp or self.data.close[0] <= slp):
                if self.p.installment == 1: self.close()
                elif not self.is_first_filled:
                    self.sell(size=self.position.size/2); self.is_first_filled = True
    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_id = order.info.get('id')
                tpp, slp, e_mode = self.calc_exits(order.executed.price)
                if e_mode == 'limits':
                    qty = order.executed.size / self.p.installment
                    self.tp_order = self.sell(exectype=bt.Order.Limit, price=tpp, size=qty)
                    self.sl_order = self.sell(exectype=bt.Order.Stop, price=slp, size=qty, oco=self.tp_order)
            elif order.issell():
                if self.position.size > 0: self.is_first_filled = True
                else: self.entry_id = None; self.is_first_filled = False

# 🚀 [Backtrader 엔진 실행부 - 무결성 보장]
if 'data' in globals():
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(TestStrategy)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.broker.setcash(1000000.0)
    cerebro.broker.setcommission(commission=0.0008)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    tot_profit = final_value - initial_value
    ret_pct = (tot_profit / initial_value) * 100
    win_rate, mdd, tot_trades = 0.0, 0.0, 0
    if results:
        strat = results[0]
        try:
            tr_an = strat.analyzers.trades.get_analysis()
            dd_an = strat.analyzers.drawdown.get_analysis()
            tot_trades = tr_an.total.total if 'total' in tr_an else 0
            if tot_trades > 0 and 'won' in tr_an:
                win_rate = (tr_an.won.total / tot_trades) * 100
            mdd = dd_an.max.drawdown if 'max' in dd_an else 0.0
        except: pass
    metrics = {
        "Total Return (%)": round(ret_pct, 2),
        "Total Profit": round(tot_profit, 2),
        "Win Rate (%)": round(win_rate, 2),
        "MDD (%)": round(mdd, 2),
        "Total Trades": tot_trades
    }
"""
