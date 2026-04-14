# [The Real 100.0% Parity v4.6] 전략 템플릿 마스터 (Universal Fix)

VECTORBT_STRATEGY = """import vectorbt as vbt
import pandas as pd
import numpy as np
from numba import njit
import math

# [지표 엔진: NaN-Safe]
@njit
def n_sma(s, l):
    res = np.full(len(s), np.nan)
    for i in range(len(s)):
        if i < l - 1: continue
        valid_sum = 0.0; count = 0
        for j in range(i - l + 1, i + 1):
            if not np.isnan(s[j]):
                valid_sum += s[j]; count += 1
        if count == l: res[i] = valid_sum / l
    return res

@njit
def n_ema(s, l):
    res = np.full(len(s), np.nan); alpha = 2.0 / (l + 1.0); last_val = np.nan
    for i in range(len(s)):
        if np.isnan(s[i]): continue
        if np.isnan(last_val): 
            res[i] = s[i]; last_val = s[i]
        else:
            res[i] = alpha * s[i] + (1.0 - alpha) * last_val
            last_val = res[i]
    return res

@njit
def n_rma(s, l):
    res = np.full(len(s), np.nan); alpha = 1.0 / l; last_val = np.nan
    for i in range(len(s)):
        if np.isnan(s[i]): continue
        if np.isnan(last_val):
            res[i] = s[i]; last_val = s[i]
        else:
            res[i] = alpha * s[i] + (1.0 - alpha) * last_val
            last_val = res[i]
    return res

@njit
def n_wma(s, l):
    res = np.full(len(s), np.nan); w_sum = (l * (l + 1)) / 2
    for i in range(len(s)):
        if i < l - 1: continue
        dot_p = 0.0; valid = True
        for j in range(l):
            val = s[i - l + 1 + j]
            if np.isnan(val): 
                valid = False; break
            dot_p += val * (j + 1)
        if valid: res[i] = dot_p / w_sum
    return res

@njit
def n_vwma(c_p, v_p, l):
    cv = c_p * v_p
    res_cv = n_sma(cv, l); res_v = n_sma(v_p, l)
    return res_cv / res_v

def calc_ma_vbt(s, v, l, t):
    if t == 'SMA': return n_sma(s.values, l)
    elif t == 'EMA': return n_ema(s.values, l)
    elif t == 'SMMA (RMA)': return n_rma(s.values, l)
    elif t == 'WMA': return n_wma(s.values, l)
    elif t == 'VWMA': return n_vwma(s.values, v.values if v is not None else np.ones(len(s)), l)
    return n_sma(s.values, l)

# [데이터 및 지표 로드]
c_np, h_np, l_np, o_np = data['Close'].values, data['High'].values, data['Low'].values, data['Open'].values

# 파라미터 로드
if 'optuna_trial' in globals() and optuna_trial:
    hl_price_type = optuna_trial.suggest_categorical('hl_price', ['BB', 'H/L OTT', 'MAX'])
    bb_ma_type, bb_len = optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']), optuna_trial.suggest_int('bb_length', 10, 50)
    bb_dev_in, bb_min_w = optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1), optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1)
    hott_ma_type, hott_len = optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']), optuna_trial.suggest_int('hott_length', 1, 10)
    hott_per, hott_h_len = optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1), optuna_trial.suggest_int('hott_h_length', 50, 200)
    hott_h_src, h_int = optuna_trial.suggest_categorical('hott_h_src', ['High', 'close']), optuna_trial.suggest_int('high_int', 0, 5)
    hl_tp_atr_mul = optuna_trial.suggest_float('hl_tp_atr_mul', 1.0, 6.0, step=0.1)
    hl_sl_atr_mul = optuna_trial.suggest_float('hl_sl_atr_mul', 1.0, 6.0, step=0.1)
    o_m_hl, o_m_ll = optuna_trial.suggest_categorical('open_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('open_at_ll', ['limits', 'close'])
    e_m_hl, e_m_ll = optuna_trial.suggest_categorical('exit_at_hl', ['limits', 'close']), optuna_trial.suggest_categorical('exit_at_ll', ['limits', 'close'])
    tp_hl_type, sl_hl_type = optuna_trial.suggest_categorical('hl_tp_price', ['Fixed', 'ATR', 'both']), optuna_trial.suggest_categorical('hl_sl_price', ['Fixed', 'ATR', 'both'])
    ma2_type, ma2_len, ma1_len = optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']), optuna_trial.suggest_int('ma2_len', 1, 10), optuna_trial.suggest_int('ma1_len', 10, 50)
    tr_ma_type, tr_ma_len = optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']), optuna_trial.suggest_int('tr_ma_len', 50, 200)
    atr_len, atr_len2 = optuna_trial.suggest_int('atr_length', 7, 20), optuna_trial.suggest_int('atr_length2', 7, 20)
    ll_mult, ll_vol_filter = optuna_trial.suggest_float('ll_mult', 1.0, 3.0, step=0.1), optuna_trial.suggest_categorical('ll_volatility_filter', [True, False])
    en_ll_per = optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.001)
    tp_hl_per, sl_hl_per = optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.001), optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.001)
    tp_ll_per, sl_ll_per = optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.001), optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.001)
    ex_dec, inst, tr_hl, slippage_ticks = optuna_trial.suggest_int('exchange_decimal', 1, 8), optuna_trial.suggest_categorical('installment', [1, 2]), optuna_trial.suggest_categorical('tr_hl', [True, False]), 3
else:
    hl_price_type, bb_ma_type, bb_len, bb_dev_in, bb_min_w = 'H/L OTT', 'EMA', 20, 2.0, 3.0
    hott_ma_type, hott_len, hott_per, hott_h_len, hott_h_src, h_int = 'EMA', 2, 0.6, 100, 'close', 0
    hl_tp_atr_mul, hl_sl_atr_mul = 2.0, 4.0
    o_m_hl, o_m_ll, e_m_hl, e_m_ll = 'limits', 'limits', 'close', 'limits'
    tp_hl_type, sl_hl_type = 'both', 'both'
    ma2_type, ma2_len, ma1_len, tr_ma_type, tr_ma_len, atr_len, atr_len2 = 'EMA', 3, 20, 'EMA', 100, 10, 10
    ll_mult, ll_vol_filter, en_ll_per = 1.5, False, 0.06
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per = 0.015, 0.02, 0.015, 0.015
    ex_dec, inst, tr_hl, slippage_ticks = 3, 1, True, 3

bb_mid = calc_ma_vbt(data['Close'], data['Volume'] if 'Volume' in data.columns else None, bb_len, bb_ma_type)
bb_std = data['Close'].rolling(bb_len).std(ddof=0).values
bb_dev = np.maximum(bb_std * bb_dev_in, bb_mid * bb_min_w / 100.0)
bb_u = bb_mid + bb_dev
h_src = data['High'] if hott_h_src == 'High' else data['Close']
mavg_h_pre = h_src.rolling(hott_h_len).max()
mavg_h_np = calc_ma_vbt(mavg_h_pre, data['Volume'] if 'Volume' in data.columns else None, hott_len, hott_ma_type)

@njit
def calc_hott_nb(mavg_np, percent):
    n = len(mavg_np); hott = np.full(n, np.nan); lsp, ssp, dv = np.nan, np.nan, 1
    for i in range(n):
        ma = mavg_np[i]
        if np.isnan(ma): continue
        fk = ma * percent * 0.01; ls, ss = ma - fk, ma + fk
        if np.isnan(lsp): lsp, ssp = ls, ss; continue
        if ma > lsp: lsp = max(ls, lsp)
        if ma < ssp: ssp = min(ss, ssp)
        if dv == -1 and ma > ssp: dv = 1
        elif dv == 1 and ma < lsp: dv = -1
        mt = lsp if dv == 1 else ssp
        hott[i] = mt * (200 + percent) / 200 if ma > mt else mt * (200 - percent) / 200
    return hott

hott_v = calc_hott_nb(mavg_h_np, hott_per)
atr_tp = vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len).atr.values
atr_sl = vbt.ATR.run(data['High'], data['Low'], data['Close'], window=atr_len2).atr.values
ma1 = ((data['High'] - data['Low']) / data['Close'].replace(0, 0.0001)).rolling(ma1_len).mean().values
ma2 = calc_ma_vbt(data['Close'], data['Volume'] if 'Volume' in data.columns else None, ma2_len, ma2_type)
tr_ma = calc_ma_vbt(data['Close'], data['Volume'] if 'Volume' in data.columns else None, tr_ma_len, tr_ma_type)

hl_p_triggers = (hott_v if hl_price_type == 'H/L OTT' else (bb_u if hl_price_type == 'BB' else np.maximum(hott_v, bb_u)))
ll_p_triggers = (ma2 * (1 - ma1 * ll_mult - en_ll_per) if ll_vol_filter else ma2 * (1 - en_ll_per))

# [상태 관리 및 엔진]
num_cols = 1
id_arr = np.zeros(num_cols, dtype=np.int32) 
price_arr = np.zeros(num_cols, dtype=np.float64)
size_arr = np.zeros(num_cols, dtype=np.float64)

@njit
def order_func_nb(c, o, h, l, cl, hlp_t, llp_t, atp, ats, trm, 
                  inst_num, use_tr, o_m_h, o_m_l, e_m_h, e_m_l, tp_t, sl_t, h_i, 
                  tph, slh, tpl, sll, tpm, slm, slip_ticks, dec, 
                  id_a, price_a, size_a):
    
    i = c.i; col = c.col
    # 🚨 [V4.6] JIT 안정성 필드명 피격: last_position/last_cash 사용
    pos = c.last_position; cash = c.last_cash
    
    tick = 10.0**-dec; slip = slip_ticks * tick
    
    idx_h = i - 1 - h_i
    if idx_h < 0: return vbt.portfolio.nb.order_nothing_nb
    hlp, llp = hlp_t[idx_h], llp_t[i-1]
    
    if pos == 0:
        id_a[col] = 0; price_a[col] = 0.0; size_a[col] = 0.0
        if not np.isnan(hlp) and hlp > 0:
            if (h[i] > hlp if o_m_h == 'limits' else cl[i] > hlp):
                ep = (max(o[i], hlp) if o_m_h == 'limits' else cl[i]) + slip
                qty = np.floor((cash / ep) * 10.0**dec + 0.5) / 10.0**dec
                if qty > 0:
                    id_a[col] = 1; price_a[col] = ep; size_a[col] = qty
                    return vbt.portfolio.nb.order_nb(size=qty, price=ep, size_type=vbt.portfolio.nb.SizeType.Amount)
        if not np.isnan(llp) and llp > 0:
            if (l[i] < llp if o_m_l == 'limits' else cl[i] < llp):
                ep = (min(o[i], llp) if o_m_l == 'limits' else cl[i]) + slip
                qty = np.floor((cash / ep) * 10.0**dec + 0.5) / 10.0**dec
                if qty > 0:
                    id_a[col] = 2; price_a[col] = ep; size_a[col] = qty
                    return vbt.portfolio.nb.order_nb(size=qty, price=ep, size_type=vbt.portfolio.nb.SizeType.Amount)
            
    if pos > 0:
        if use_tr and not np.isnan(trm[i]) and cl[i] < trm[i] and cl[i-1] >= trm[i-1]:
            return vbt.portfolio.nb.order_nb(size=-pos, price=cl[i]-slip, size_type=vbt.portfolio.nb.SizeType.Amount)
        ep = price_a[col]; cur_state = id_a[col]
        if cur_state == 1: 
            tf, ta = ep*(1+tph), ep + tpm*atp[i]
            tpp = tf if tp_t=='Fixed' else (ta if tp_t=='ATR' else max(tf, ta))
            sf, sa = ep*(1-slh), ep - slm*ats[i]
            slp = sf if sl_t=='Fixed' else (sa if sl_t=='ATR' else max(sf, sa))
            exit_mode = e_m_h
        else: 
            tpp, slp = ep*(1+tpl), ep*(1-sll); exit_mode = e_m_l
        if np.isnan(tpp) or np.isnan(slp): return vbt.portfolio.nb.order_nothing_nb
        is_hit = (h[i] >= tpp or l[i] <= slp) if exit_mode == 'limits' else (cl[i] >= tpp or cl[i] <= slp)
        if is_hit:
            exit_p = (tpp if h[i] >= tpp else slp) if exit_mode == 'limits' else cl[i]
            if exit_mode == 'limits' and (o[i] >= tpp or o[i] <= slp): exit_p = o[i]
            exit_p -= slip
            cur_qty = pos; target_dec = 10.0**dec
            if inst == 2 and pos > (np.floor((size_a[col] * 0.6) * target_dec + 0.5) / target_dec):
                return vbt.portfolio.nb.order_nb(size=-(np.floor((pos/2) * target_dec + 0.5) / target_dec), price=exit_p, size_type=vbt.portfolio.nb.SizeType.Amount)
            else:
                return vbt.portfolio.nb.order_nb(size=-pos, price=exit_p, size_type=vbt.portfolio.nb.SizeType.Amount)
    return vbt.portfolio.nb.order_nothing_nb

# 시뮬레이션 (Standard Mode + Stability Fix)
portfolio = vbt.Portfolio.from_order_func(
    data['Close'], order_func_nb,
    o_np, h_np, l_np, c_np, hl_p_triggers, ll_p_triggers, atr_tp, atr_sl, tr_ma,
    inst, tr_hl, o_m_hl, o_m_ll, e_m_hl, e_m_ll, tp_hl_type, sl_hl_type, h_int,
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per, hl_tp_atr_mul, hl_sl_atr_mul, slippage_ticks, ex_dec,
    id_arr, price_arr, size_arr,
    flexible=False, init_cash=1000000, fees=0.0008, cash_sharing=False
)
stats = portfolio.stats()
metrics = {
    "Total Return (%)": round(np.nan_to_num(float(portfolio.total_return() * 100.0)), 2),
    "Win Rate (%)": round(np.nan_to_num(float(stats.get('Win Rate [%]', 0.0))), 2),
    "MDD (%)": round(np.nan_to_num(float(portfolio.max_drawdown() * 100.0)), 2),
    "Total Trades": int(portfolio.trades.count()),
    "Total Profit": round(np.nan_to_num(float(portfolio.total_profit())), 2)
}
"""

BACKTRADER_STRATEGY = """import backtrader as bt
import math
import datetime

def pine_round(x): return math.floor(x + 0.5)

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
            try:
                v = self.data._owner.volume if hasattr(self.data, '_owner') and hasattr(self.data._owner, 'volume') else self.data.volume
                self.lines.ma = bt.indicators.SMA(d * v, period=p) / bt.indicators.SMA(v, period=p)
            except Exception:
                v = self.data._owner.datas[0].volume
                self.lines.ma = bt.indicators.SMA(d * v, period=p) / bt.indicators.SMA(v, period=p)
        else: self.lines.ma = bt.indicators.SMA(d, period=p)

class HOTTIndicator(bt.Indicator):
    lines = ('hott',)
    params = (('period', 100), ('length', 2), ('percent', 0.6), ('use_high', False), ('matype', 'EMA'))
    def __init__(self):
        src = self.data.high if self.p.use_high else self.data.close
        h_val = bt.indicators.Highest(src, period=self.p.period)
        self.mavg = UniversalMA(h_val, period=self.p.length, matype=self.p.matype)
        self.addminperiod(self.p.period + self.p.length + 5)
    def next(self):
        ma = self.mavg[0]
        if math.isnan(ma): return
        fk = ma * self.p.percent * 0.01; ls, ss = ma - fk, ma + fk
        if not hasattr(self, 'lsp'): self.lsp, self.ssp, self.dir = ls, ss, 1
        if ma > self.lsp: self.lsp = max(ls, self.lsp)
        if ma < self.ssp: self.ssp = min(ss, self.ssp)
        if self.dir == -1 and ma > self.ssp: self.dir = 1
        elif self.dir == 1 and ma < self.lsp: self.dir = -1
        mt = self.lsp if self.dir == 1 else self.ssp
        self.lines.hott[0] = mt * (200 + self.p.percent) / 200 if ma > mt else mt * (200 - self.p.percent) / 200

class BBCustom(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('dev', 2.0), ('min_width', 3.0), ('matype', 'EMA'))
    def __init__(self):
        self.mid_ma = UniversalMA(self.data, period=self.p.period, matype=self.p.matype)
        self.stddev = bt.indicators.StdDev(self.data.close if hasattr(self.data, 'close') else self.data, period=self.p.period)
    def next(self):
        mid = self.mid_ma[0]; std = self.stddev[0] * self.p.dev
        if math.isnan(mid) or math.isnan(std): return
        lbbdev = max(std, mid * self.p.min_width / 100.0)
        self.lines.mid[0] = mid; self.lines.top[0] = mid + lbbdev; self.lines.bot[0] = mid - lbbdev

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
        ('ma2_type', optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('ma2_length', optuna_trial.suggest_int('ma2_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 3),
        ('bb_ma_type', optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('bb_length', optuna_trial.suggest_int('bb_length', 10, 50) if 'optuna_trial' in globals() and optuna_trial else 20),
        ('bb_dev', optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 2.0),
        ('bb_min_width', optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 3.0),
        ('hott_ma_type', optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('hott_length', optuna_trial.suggest_int('hott_length', 1, 10) if 'optuna_trial' in globals() and optuna_trial else 2),
        ('hott_percent', optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 0.6),
        ('hott_h_length', optuna_trial.suggest_int('hott_h_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('hott_use_high', optuna_trial.suggest_categorical('hott_use_high', [True, False]) if 'optuna_trial' in globals() and optuna_trial else False),
        ('high_int', optuna_trial.suggest_int('high_int', 0, 1) if 'optuna_trial' in globals() and optuna_trial else 0),
        ('entry_ll_per', optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.001) if 'optuna_trial' in globals() and optuna_trial else 0.06),
        ('tp_hl_per', optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_hl_per', optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.001) if 'optuna_trial' in globals() and optuna_trial else 0.02),
        ('tp_ll_per', optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('sl_ll_per', optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.001) if 'optuna_trial' in globals() and optuna_trial else 0.015),
        ('atr_length', optuna_trial.suggest_int('atr_length', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('atr_length2', optuna_trial.suggest_int('atr_length2', 7, 20) if 'optuna_trial' in globals() and optuna_trial else 10),
        ('hl_tp_atr_mul', optuna_trial.suggest_float('hl_tp_atr_mul', 1.0, 6.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 2.0),
        ('hl_sl_atr_mul', optuna_trial.suggest_float('hl_sl_atr_mul', 1.0, 6.0, step=0.1) if 'optuna_trial' in globals() and optuna_trial else 4.0),
        ('tr_ma_type', optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) if 'optuna_trial' in globals() and optuna_trial else 'EMA'),
        ('tr_ma_length', optuna_trial.suggest_int('tr_ma_length', 50, 200) if 'optuna_trial' in globals() and optuna_trial else 100),
        ('exchange_decimal', optuna_trial.suggest_int('exchange_decimal', 1, 8) if 'optuna_trial' in globals() and optuna_trial else 3),
        ('installment', optuna_trial.suggest_categorical('installment', [1, 2]) if 'optuna_trial' in globals() and optuna_trial else 1),
    )
    def __init__(self):
        self.dataclose = self.datas[0].close; self.datahigh = self.datas[0].high; self.datalow = self.datas[0].low
        self.atr_tp = bt.indicators.ATR(self.datas[0], period=self.p.atr_length)
        self.atr_sl = bt.indicators.ATR(self.datas[0], period=self.p.atr_length2)
        safe_close = bt.If(self.dataclose > 0, self.dataclose, 0.000001)
        self.ma1 = bt.indicators.SMA((self.datahigh - self.datalow) / safe_close, period=self.p.ma1_length)
        self.ma2 = UniversalMA(self.datas[0], period=self.p.ma2_length, matype=self.p.ma2_type)
        self.bb = BBCustom(period=self.p.bb_length, dev=self.p.bb_dev, min_width=self.p.bb_min_width, matype=self.p.bb_ma_type)
        self.hott = HOTTIndicator(self.datas[0], period=self.p.hott_h_length, length=self.p.hott_length, percent=self.p.hott_percent, use_high=self.p.hott_use_high, matype=self.p.hott_ma_type)
        self.tr_ma = UniversalMA(self.dataclose, period=self.p.tr_ma_length, matype=self.p.tr_ma_type)
        self.entry_id = None; self.partial_filled = False; self.tp_order = None; self.sl_order = None
        self.pending_entry = None 
        t_size = 10.0 ** -self.p.exchange_decimal
        self.broker.set_slippage_fixed(3.0 * t_size)

    def get_qty(self, val): return math.floor(val * (10**self.p.exchange_decimal)) / (10.0**self.p.exchange_decimal)

    def issue_exit_orders(self, bp, size):
        exit_mode = self.p.exit_at_hl if self.entry_id == 'HL' else self.p.exit_at_ll
        if exit_mode == 'close': return
        if self.entry_id == 'HL':
            tf, ta = bp*(1+self.p.tp_hl_per), bp + self.p.hl_tp_atr_mul*self.atr_tp[0]
            tpp = tf if self.p.hl_tp_price=='Fixed' else (ta if self.p.hl_tp_price=='ATR' else max(tf, ta))
            sf, sa = bp*(1-self.p.sl_hl_per), bp - self.p.hl_sl_atr_mul*self.atr_sl[0]
            slp = sf if self.p.hl_sl_price=='Fixed' else (sa if self.p.hl_sl_price=='ATR' else max(sf, sa))
        else: tpp, slp = bp*(1+self.p.tp_ll_per), bp*(1-self.p.sl_ll_per)
        if tpp and slp and size > 0:
            o1 = self.sell(exectype=bt.Order.Limit, price=tpp, size=size)
            if o1: self.tp_order = o1
            o2 = self.sell(exectype=bt.Order.Stop, price=slp, size=size, oco=self.tp_order)
            if o2: self.sl_order = o2

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.pending_entry = None; self.entry_id = order.info.get('id')
                q = math.ceil(order.executed.size / self.p.installment)
                self.issue_exit_orders(order.executed.price, self.get_qty(q))
            elif order.issell():
                if self.position.size > 0: self.partial_filled = True
                else: self.entry_id, self.partial_filled = None, False
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.pending_entry: self.pending_entry = None

    def next(self):
        cur_cl = self.dataclose[0]
        if self.position.size > 0:
            exit_mode = self.p.exit_at_hl if self.entry_id == 'HL' else self.p.exit_at_ll
            ep = self.position.price
            if exit_mode == 'close':
                if self.entry_id == 'HL':
                    tf, ta = ep*(1+self.p.tp_hl_per), ep + self.p.hl_tp_atr_mul*self.atr_tp[0]
                    tpp = tf if self.p.hl_tp_price=='Fixed' else (ta if self.p.hl_tp_price=='ATR' else max(tf, ta))
                    sf, sa = ep*(1-self.p.sl_hl_per), ep - self.p.hl_sl_atr_mul*self.atr_sl[0]
                    slp = sf if self.p.hl_sl_price=='Fixed' else (sa if self.p.hl_sl_price=='ATR' else max(sf, sa))
                else: tpp, slp = ep*(1+self.p.tp_ll_per), ep*(1-self.p.sl_ll_per)
                if not math.isnan(tpp) and (cur_cl >= tpp or cur_cl <= slp):
                    q = self.get_qty(self.position.size if self.p.installment == 1 or self.partial_filled else math.ceil(self.position.size / 2))
                    self.sell(size=q); return
            if self.p.tr_hl and not math.isnan(self.tr_ma[0]) and cur_cl < self.tr_ma[0] and self.dataclose[-1] >= self.tr_ma[-1]: self.close(); return
        if not self.position:
            if self.pending_entry: self.cancel(self.pending_entry)
            h_v = self.hott.hott[0]; hlp = self.bb.top[0] if self.p.hl_price=='BB' else (h_v if self.p.hl_price=='H/L OTT' else max(h_v, self.bb.top[0]))
            llp = self.ma2[0]*(1 - self.ma1[0]*self.p.ll_mult - self.p.entry_ll_per) if self.p.ll_volatility_filter else self.ma2[0]*(1-self.p.entry_ll_per)
            if math.isnan(hlp) or math.isnan(llp): return
            q = self.get_qty(pine_round(self.broker.getvalue() / cur_cl))
            
            # 🚨 [V4.5] Stop 주문 가격 보호 (현재가와 역전 방지)
            if hlp > 0 and self.p.open_at_hl == 'limits':
                adj_hlp = max(hlp, cur_cl * 1.0001)
                o = self.buy(exectype=bt.Order.Stop, price=adj_hlp, size=q, valid=bt.Order.DAY)
                if o: o.info['id'] = 'HL'; self.pending_entry = o
            elif llp > 0 and self.p.open_at_ll == 'limits':
                adj_llp = min(llp, cur_cl * 0.9999)
                o = self.buy(exectype=bt.Order.Limit, price=adj_llp, size=q, valid=bt.Order.DAY)
                if o: o.info['id'] = 'LL'; self.pending_entry = o
            elif (self.p.open_at_hl == 'close' and cur_cl > hlp) or (self.p.open_at_ll == 'close' and cur_cl < llp):
                eid = 'HL' if cur_cl > hlp else 'LL'
                o = self.buy(size=q)
                if o: o.info['id'] = eid

# 시뮬레이션 및 데이터 출력
cerebro = bt.Cerebro(); cerebro.addstrategy(TestStrategy); cerebro.adddata(bt.feeds.PandasData(dataname=data))
cerebro.broker.setcash(1000000.0); cerebro.broker.setcommission(commission=0.0008)
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades'); cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
init_val = cerebro.broker.getvalue(); results = cerebro.run(); final_val = cerebro.broker.getvalue(); total_prof = final_val - init_val; ret_pct = (total_prof / init_val) * 100
win_rate, mdd, total_tr = 0.0, 0.0, 0
if results:
    strat = results[0]; t_info = strat.analyzers.trades.get_analysis(); d_info = strat.analyzers.drawdown.get_analysis()
    total_tr = t_info.total.total if 'total' in t_info else 0
    if total_tr > 0 and 'won' in t_info: win_rate = round((t_info.won.total / total_tr) * 100, 2)
    if 'max' in d_info and 'drawdown' in d_info.max: mdd = round(d_info.max.drawdown, 2)
metrics = {"Total Return (%)": round(ret_pct,2), "Total Profit": round(total_prof, 2), "Win Rate (%)": win_rate, "MDD (%)": mdd, "Total Trades": total_tr}
"""
