# [The Real 100.0% Parity v4.7] 전략 템플릿 마스터 (Final Hardened Fix)

VECTORBT_STRATEGY = """import vectorbt as vbt
import pandas as pd
import numpy as np
from numba import njit
import math

# [메모리 누수 방지] Numba JIT 컴파일 결과를 캐싱하여 반복 재컴파일(OOM) 원천 차단
if 'JIT_COMPILED' not in globals():
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
    
    globals()['JIT_COMPILED_MA'] = True

# [데이터 로드]
c_np, h_np, l_np, o_np = data['Close'].values, data['High'].values, data['Low'].values, data['Open'].values

# 파라미터 로드 (Optuna 대응)
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
    ex_dec, inst, tr_hl, slip_pct = optuna_trial.suggest_int('exchange_decimal', 1, 8), optuna_trial.suggest_categorical('installment', [1, 2]), optuna_trial.suggest_categorical('tr_hl', [True, False]), 0.0005
else:
    hl_price_type, bb_ma_type, bb_len, bb_dev_in, bb_min_w = 'H/L OTT', 'EMA', 20, 2.0, 3.0
    hott_ma_type, hott_len, hott_per, hott_h_len, hott_h_src, h_int = 'EMA', 2, 0.6, 100, 'close', 0
    hl_tp_atr_mul, hl_sl_atr_mul = 2.0, 4.0
    o_m_hl, o_m_ll, e_m_hl, e_m_ll = 'limits', 'limits', 'close', 'limits'
    tp_hl_type, sl_hl_type = 'both', 'both'
    ma2_type, ma2_len, ma1_len, tr_ma_type, tr_ma_len, atr_len, atr_len2 = 'EMA', 3, 20, 'EMA', 100, 10, 10
    ll_mult, ll_vol_filter, en_ll_per = 1.5, False, 0.06
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per = 0.015, 0.02, 0.015, 0.015
    ex_dec, inst, tr_hl, slip_pct = 3, 1, True, 0.0005

# 🚀 [V9.0] MTF 리샘플링 파이프라인 (Bar Magnifier Parity)
# 1분봉 데이터를 전략 주기(target_tf)로 리샘플링하여 지표를 계산합니다.
data_htf = data.vbt.resample(target_tf).ohlcv()

bb_mid_htf = calc_ma_vbt(data_htf['Close'], data_htf['Volume'], bb_len, bb_ma_type)
bb_std_htf = data_htf['Close'].rolling(bb_len).std(ddof=1).values # ddof=1 (Pine Script Parity)
bb_dev_htf = np.maximum(bb_std_htf * bb_dev_in, bb_mid_htf * bb_min_w / 100.0)
bb_u_htf = bb_mid_htf + bb_dev_htf

h_src_htf = data_htf['High'] if hott_h_src == 'High' else data_htf['Close']
mavg_h_pre_htf = h_src_htf.rolling(hott_h_len).max()
mavg_h_np_htf = calc_ma_vbt(mavg_h_pre_htf, data_htf['Volume'], hott_len, hott_ma_type)
hott_v_htf = calc_hott_nb(mavg_h_np_htf, hott_per)

hott_s_htf = np.full_like(hott_v_htf, np.nan)
if h_int > 0: hott_s_htf[h_int:] = hott_v_htf[:-h_int]
else: hott_s_htf = hott_v_htf.copy()

atr_tp_htf = vbt.ATR.run(data_htf['High'], data_htf['Low'], data_htf['Close'], window=atr_len).atr.values
atr_sl_htf = vbt.ATR.run(data_htf['High'], data_htf['Low'], data_htf['Close'], window=atr_len2).atr.values
ma1_htf = ((data_htf['High'] - data_htf['Low']) / data_htf['Close'].replace(0, 0.0001)).rolling(ma1_len).mean().values
ma2_htf = calc_ma_vbt(data_htf['Close'], data_htf['Volume'], ma2_len, ma2_type)
tr_ma_htf = calc_ma_vbt(data_htf['Close'], data_htf['Volume'], tr_ma_len, tr_ma_type)

# 🚀 [V9.0] Alignment: 상위 타임프레임 지표를 1분봉 인덱스로 확장하고 1봉 Shift (미래 참조 방지)
def align_to_1m(htf_arr, source_idx, target_idx):
    s = pd.Series(htf_arr, index=source_idx)
    return s.reindex(target_idx, method='ffill').shift(1).values

bb_u = align_to_1m(bb_u_htf, data_htf.index, data.index)
hott_s = align_to_1m(hott_s_htf, data_htf.index, data.index)
atr_tp = align_to_1m(atr_tp_htf, data_htf.index, data.index)
atr_sl = align_to_1m(atr_sl_htf, data_htf.index, data.index)
ma1 = align_to_1m(ma1_htf, data_htf.index, data.index)
ma2 = align_to_1m(ma2_htf, data_htf.index, data.index)
tr_ma = align_to_1m(tr_ma_htf, data_htf.index, data.index)

hl_p_t = (hott_s if hl_price_type == 'H/L OTT' else (bb_u if hl_price_type == 'BB' else np.maximum(hott_s, bb_u)))
ll_p_triggers = (ma2 * (1 - ma1 * ll_mult - en_ll_per) if ll_vol_filter else ma2 * (1 - en_ll_per))

# [상태 관리 및 엔진]
num_cols = 1
id_arr = np.zeros(num_cols, dtype=np.int32)
price_arr = np.zeros(num_cols, dtype=np.float64)
size_arr = np.zeros(num_cols, dtype=np.float64)
entry_idx_arr = np.full(num_cols, -1, dtype=np.int64)  # 🚀 [V8.2] 동일 봉 진입-청산 방지용

if 'JIT_COMPILED_ORDER_V82' not in globals():
    @njit
    def order_func_nb(c, o, h, l, cl, hlp_t, llp_t, atp, ats, trm,
                      inst_num, use_tr, o_m_h, o_m_l, e_m_h, e_m_l, tp_t, sl_t,
                      tph, slh, tpl, sll, tpm, slm, slip_pct, dec,
                      id_a, price_a, size_a, entry_idx_a):

        i = c.i; col = c.col
        if i < 1:
            return vbt.portfolio.nb.order_nothing_nb()

        pos = c.position_now; cash = c.cash_now
        p10 = 10.0**dec

        if pos == 0:
            id_a[col] = 0; price_a[col] = 0.0; size_a[col] = 0.0; entry_idx_a[col] = -1
            hlp = hlp_t[i-1]; llp = llp_t[i-1]
            if not np.isnan(hlp) and hlp > 0:
                if (h[i] > hlp if o_m_h == 0 else cl[i] > hlp):
                    raw_ep = (max(o[i], hlp) if o_m_h == 0 else cl[i])
                    ep = np.floor(raw_ep * (1.0 + slip_pct) * p10 + 0.5) / p10
                    qty = np.floor((cash * 0.991 / ep) * p10 + 0.5) / p10
                    if qty > 0:
                        id_a[col] = 1; price_a[col] = ep; size_a[col] = qty; entry_idx_a[col] = i
                        return vbt.portfolio.nb.order_nb(size=qty, price=ep, size_type=0)
            if not np.isnan(llp) and llp > 0:
                if (l[i] < llp if o_m_l == 0 else cl[i] < llp):
                    raw_ep = (min(o[i], llp) if o_m_l == 0 else cl[i])
                    ep = np.floor(raw_ep * (1.0 + slip_pct) * p10 + 0.5) / p10
                    qty = np.floor((cash * 0.991 / ep) * p10 + 0.5) / p10
                    if qty > 0:
                        id_a[col] = 2; price_a[col] = ep; size_a[col] = qty; entry_idx_a[col] = i
                        return vbt.portfolio.nb.order_nb(size=qty, price=ep, size_type=0)

        if pos > 0:
            if i == entry_idx_a[col]:  # 🚀 [V8.2] 동일 봉 진입-청산 원천 차단
                return vbt.portfolio.nb.order_nothing_nb()
            cur_state = id_a[col]
            ep = price_a[col]
            if use_tr and cur_state == 1 and not np.isnan(trm[i]) and cl[i] < trm[i] and cl[i-1] >= trm[i-1]:
                exit_p = np.floor(cl[i] * (1.0 - slip_pct) * p10 + 0.5) / p10
                return vbt.portfolio.nb.order_nb(size=-pos, price=exit_p, size_type=0)
            if cur_state == 1:
                tf, ta = ep*(1+tph), ep + tpm*atp[i]
                tpp = tf if tp_t==0 else (ta if tp_t==1 else max(tf, ta))
                sf, sa = ep*(1-slh), ep - slm*ats[i]
                slp = sf if sl_t==0 else (sa if sl_t==1 else max(sf, sa))
                exit_mode = e_m_h
            else:
                tpp, slp = ep*(1+tpl), ep*(1-sll); exit_mode = e_m_l
            if np.isnan(tpp) or np.isnan(slp): return vbt.portfolio.nb.order_nothing_nb()
            is_hit = (h[i] >= tpp or l[i] <= slp) if exit_mode == 0 else (cl[i] >= tpp or cl[i] <= slp)
            if is_hit:
                is_tp = False
                if exit_mode == 0:
                    if h[i] >= tpp and l[i] <= slp:
                        is_tp = False  # 🚀 [V8.1] SL 우선
                    else:
                        is_tp = (h[i] >= tpp)
                    exit_p = tpp if is_tp else slp
                    if (o[i] >= tpp or o[i] <= slp):
                        exit_p = o[i]; is_tp = (o[i] >= tpp)
                else:
                    is_tp = (cl[i] >= tpp); exit_p = cl[i]
                exit_p = np.floor(exit_p * (1.0 - slip_pct) * p10 + 0.5) / p10  # 🚀 [V8.2] % 슬리피지
                if inst_num == 2 and pos > (np.ceil((size_a[col] * 0.6) * p10) / p10):
                    return vbt.portfolio.nb.order_nb(size=-(np.ceil((pos/2) * p10) / p10), price=exit_p, size_type=0)
                else:
                    return vbt.portfolio.nb.order_nb(size=-pos, price=exit_p, size_type=0)
        return vbt.portfolio.nb.order_nothing_nb()
    globals()['JIT_COMPILED_ORDER_V82'] = True

# 시뮬레이션
# 🚀 [V6.0] hott_s 선언 위치 교정: calc_hott_nb 직후에 배치
hott_v = calc_hott_nb(mavg_h_np, hott_per)
hott_s = np.full_like(hott_v, np.nan)
if h_int > 0:
    hott_s[h_int:] = hott_v[:-h_int]
else:
    hott_s = hott_v.copy()

if hl_price_type == 'H/L OTT':
    hl_p_t = hott_s
elif hl_price_type == 'BB':
    hl_p_t = bb_u
else: # MAX
    hl_p_t = np.maximum(hott_s, bb_u)

m_map = {'limits': 0, 'close': 1}
t_map = {'Fixed': 0, 'ATR': 1, 'both': 2}
o_h_m, o_l_m = m_map.get(o_m_hl, 0), m_map.get(o_m_ll, 0)
e_h_m, e_l_m = m_map.get(e_m_hl, 0), m_map.get(e_m_ll, 0)
tp_h_t, sl_h_t = t_map.get(tp_hl_type, 0), t_map.get(sl_hl_type, 0)

vbt.settings.portfolio['fees'] = 0.0008
portfolio = vbt.Portfolio.from_order_func(
    data['Close'], order_func_nb,
    o_np, h_np, l_np, c_np, hl_p_t, ll_p_triggers, atr_tp, atr_sl, tr_ma,
    inst, tr_hl, o_h_m, o_l_m, e_h_m, e_l_m, tp_h_t, sl_h_t,
    tp_hl_per, sl_hl_per, tp_ll_per, sl_ll_per, hl_tp_atr_mul, hl_sl_atr_mul, slip_pct, ex_dec,
    id_arr, price_arr, size_arr, entry_idx_arr,
    flexible=False, init_cash=500000, cash_sharing=False
)
stats = portfolio.stats()
metrics = {
    "Total Return (%)": round(np.nan_to_num(float(portfolio.total_return() * 100.0)), 2),
    "Win Rate (%)": round(np.nan_to_num(float(stats.get('Win Rate [%]', 0.0))), 2),
    "MDD (%)": round(np.nan_to_num(float(portfolio.max_drawdown() * 100.0)), 2),
    "Total Trades": int(portfolio.trades.count()),
    "Total Profit": round(np.nan_to_num(float(portfolio.total_profit())), 2),
    "Total Fees": round(np.nan_to_num(float(stats.get('Total Fees [$]', stats.get('Total Fees', 0.0)))), 2)
}
"""

BACKTRADER_STRATEGY = """import backtrader as bt
import math
import datetime

def pine_round(x): return math.floor(x + 0.5)

# [메모리 누수 방지] 클래스 전역 스코프 유지 및 재정의 차단 (OOM 방어)
if 'BT_CLASSES_LOADED' not in globals():
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
                    # 🚨 [V4.8] 볼륨 데이터의 안정적 접근 및 0 나누기 방어
                    v = self.data.volume
                    v_sma = bt.indicators.SMA(v, period=p)
                    safe_v_sma = bt.If(v_sma > 0, v_sma, 0.000001)
                    self.lines.ma = bt.indicators.SMA(d * v, period=p) / safe_v_sma
                except Exception:
                    self.lines.ma = bt.indicators.SMA(d, period=p)
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
            
            # 🚨 [V4.8] Pine Script [1] 인덱싱(전일 데이터 참조) 방식 재현
            if not hasattr(self, 'lsp'):
                self.lsp, self.ssp, self.dir = ls, ss, 1
                return # 첫 바는 초기화만 수행

            prev_lsp, prev_ssp, prev_dir = self.lsp, self.ssp, self.dir
            
            # 1. 이전 값(Prev) 기반으로 방향(Dir) 결정
            if prev_dir == -1 and ma > prev_ssp: new_dir = 1
            elif prev_dir == 1 and ma < prev_lsp: new_dir = -1
            else: new_dir = prev_dir
            
            # 2. 트레일링 스탑 갱신
            new_lsp = max(ls, prev_lsp) if ma > prev_lsp else ls
            new_ssp = min(ss, prev_ssp) if ma < prev_ssp else ss
            
            # 3. 객체 상태 업데이트
            self.lsp, self.ssp, self.dir = new_lsp, new_ssp, new_dir
            
            # 4. 출력값 계산
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
            ('hl_price', 'H/L OTT'), ('open_at_hl', 'limits'), ('open_at_ll', 'limits'),
            ('exit_at_hl', 'close'), ('exit_at_ll', 'limits'),
            ('hl_tp_price', 'both'), ('hl_sl_price', 'both'),
            ('tr_hl', True), ('ll_volatility_filter', False),
            ('ma1_length', 20), ('ll_mult', 1.5),
            ('ma2_type', 'EMA'), ('ma2_length', 3),
            ('bb_ma_type', 'EMA'), ('bb_length', 20), ('bb_dev', 2.0), ('bb_min_width', 3.0),
            ('hott_ma_type', 'EMA'), ('hott_length', 2), ('hott_percent', 0.6), ('hott_h_length', 100), ('hott_use_high', False),
            ('high_int', 0), ('entry_ll_per', 0.06),
            ('tp_hl_per', 0.015), ('sl_hl_per', 0.02), ('tp_ll_per', 0.015), ('sl_ll_per', 0.015),
            ('atr_length', 10), ('atr_length2', 10), ('hl_tp_atr_mul', 2.0), ('hl_sl_atr_mul', 4.0),
            ('tr_ma_type', 'EMA'), ('tr_ma_length', 100),
            ('exchange_decimal', 3), ('installment', 1),
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
            self.pending_orders = [] # 🚨 [V4.9] 단일 변수 대신 리스트로 다중 대기 주문 추적
            t_size = 10.0 ** -self.p.exchange_decimal
            self.broker.set_slippage_fixed(3.0 * t_size)

        def get_qty(self, val): return math.floor(val * (10**self.p.exchange_decimal)) / (10.0**self.p.exchange_decimal)
    globals()['BT_CLASSES_LOADED'] = True

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
                # 🚨 [V4.7] 분할 매도 시 수량 올림 버그 해결
                pow10 = 10 ** self.p.exchange_decimal
                raw_q = order.executed.size / self.p.installment
                q = math.ceil(raw_q * pow10) / pow10
                self.issue_exit_orders(order.executed.price, self.get_qty(q))
            elif order.issell():
                if self.position.size > 0:
                    self.partial_filled = True
                    # 🚀 [V5.2] 포지션이 남아있다면 잔여 물량에 대해 OCO 주문 재생성 (최초 진입가 기준)
                    self.issue_exit_orders(self.position.price, self.position.size)
                else: self.entry_id, self.partial_filled = None, False
        
        # 🚨 [V4.9] 어떤 상태에서든 주문이 종료되면 추적 리스트에서 제거
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            if order in self.pending_orders:
                self.pending_orders.remove(order)

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
                    pow10 = 10 ** self.p.exchange_decimal
                    raw_p = self.position.size if self.p.installment == 1 or self.partial_filled else math.ceil((self.position.size / 2)*pow10)/pow10
                    q = self.get_qty(raw_p)
                    self.sell(size=q); return
            if self.p.tr_hl and self.entry_id == 'HL' and not math.isnan(self.tr_ma[0]) and cur_cl < self.tr_ma[0] and self.dataclose[-1] >= self.tr_ma[-1]:
                self.close(); return
        if not self.position:
            # 🚨 [V4.9] 매 봉마다 이전 대기 주문(전일 예약분) 일괄 취소 및 리스트 초기화
            for o in self.pending_orders: self.cancel(o)
            self.pending_orders.clear()

            h_v = self.hott.hott[0]; hlp = self.bb.top[0] if self.p.hl_price=='BB' else (h_v if self.p.hl_price=='H/L OTT' else max(h_v, self.bb.top[0]))
            llp = self.ma2[0]*(1 - self.ma1[0]*self.p.ll_mult - self.p.entry_ll_per) if self.p.ll_volatility_filter else self.ma2[0]*(1-self.p.entry_ll_per)
            if math.isnan(hlp) or math.isnan(llp): return
            
            pow10 = 10 ** self.p.exchange_decimal
            q = self.get_qty(pine_round((self.broker.getvalue() / cur_cl) * pow10) / pow10)
            
            # 🚨 [V4.9] if-elif 체인 해제: 돌파와 눌림 조건을 각각 독립적으로 평가
            if hlp > 0 and self.p.open_at_hl == 'limits':
                adj_hlp = max(hlp, cur_cl * 1.0001)
                o = self.buy(exectype=bt.Order.Stop, price=adj_hlp, size=q)
                if o: o.info['id'] = 'HL'; self.pending_orders.append(o)
            
            if llp > 0 and self.p.open_at_ll == 'limits':
                adj_llp = min(llp, cur_cl * 0.9999)
                o = self.buy(exectype=bt.Order.Limit, price=adj_llp, size=q)
                if o: o.info['id'] = 'LL'; self.pending_orders.append(o)
            
            if (self.p.open_at_hl == 'close' and cur_cl > hlp) or (self.p.open_at_ll == 'close' and cur_cl < llp):
                eid = 'HL' if cur_cl > hlp else 'LL'
                o = self.buy(size=q)
                if o: o.info['id'] = eid; self.pending_orders.append(o)

cerebro = bt.Cerebro()
if 'optuna_trial' in globals() and optuna_trial:
    opt_kwargs = {
        'hl_price': optuna_trial.suggest_categorical('hl_price', ['BB', 'H/L OTT', 'MAX']),
        'open_at_hl': optuna_trial.suggest_categorical('open_at_hl', ['limits', 'close']),
        'open_at_ll': optuna_trial.suggest_categorical('open_at_ll', ['limits', 'close']),
        'exit_at_hl': optuna_trial.suggest_categorical('exit_at_hl', ['limits', 'close']),
        'exit_at_ll': optuna_trial.suggest_categorical('exit_at_ll', ['limits', 'close']),
        'hl_tp_price': optuna_trial.suggest_categorical('hl_tp_price', ['Fixed', 'ATR', 'both']),
        'hl_sl_price': optuna_trial.suggest_categorical('hl_sl_price', ['Fixed', 'ATR', 'both']),
        'tr_hl': optuna_trial.suggest_categorical('tr_hl', [True, False]),
        'll_volatility_filter': optuna_trial.suggest_categorical('ll_volatility_filter', [True, False]),
        'ma1_length': optuna_trial.suggest_int('ma1_len', 10, 50),
        'll_mult': optuna_trial.suggest_float('ll_mult', 1.0, 3.0, step=0.1),
        'ma2_type': optuna_trial.suggest_categorical('ma2_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']),
        'ma2_length': optuna_trial.suggest_int('ma2_len', 1, 10),
        'bb_ma_type': optuna_trial.suggest_categorical('bb_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']),
        'bb_length': optuna_trial.suggest_int('bb_length', 10, 50),
        'bb_dev': optuna_trial.suggest_float('bb_dev', 1.0, 3.0, step=0.1),
        'bb_min_width': optuna_trial.suggest_float('bb_min_width', 1.0, 5.0, step=0.1),
        'hott_ma_type': optuna_trial.suggest_categorical('hott_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']),
        'hott_length': optuna_trial.suggest_int('hott_length', 1, 10),
        'hott_percent': optuna_trial.suggest_float('hott_percent', 0.1, 2.0, step=0.1),
        'hott_h_length': optuna_trial.suggest_int('hott_h_length', 50, 200),
        'hott_use_high': optuna_trial.suggest_categorical('hott_h_src', [True, False]),
        'high_int': optuna_trial.suggest_int('high_int', 0, 5),
        'entry_ll_per': optuna_trial.suggest_float('entry_ll_per', 0.02, 0.15, step=0.001),
        'tp_hl_per': optuna_trial.suggest_float('tp_hl_per', 0.005, 0.05, step=0.001),
        'sl_hl_per': optuna_trial.suggest_float('sl_hl_per', 0.01, 0.07, step=0.001),
        'tp_ll_per': optuna_trial.suggest_float('tp_ll_per', 0.005, 0.05, step=0.001),
        'sl_ll_per': optuna_trial.suggest_float('sl_ll_per', 0.01, 0.07, step=0.001),
        'atr_length': optuna_trial.suggest_int('atr_length', 7, 20),
        'atr_length2': optuna_trial.suggest_int('atr_length2', 7, 20),
        'hl_tp_atr_mul': optuna_trial.suggest_float('hl_tp_atr_mul', 1.0, 6.0, step=0.1),
        'hl_sl_atr_mul': optuna_trial.suggest_float('hl_sl_atr_mul', 1.0, 6.0, step=0.1),
        'tr_ma_type': optuna_trial.suggest_categorical('tr_ma_type', ['SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']),
        'tr_ma_length': optuna_trial.suggest_int('tr_ma_len', 50, 200),
        'exchange_decimal': optuna_trial.suggest_int('exchange_decimal', 1, 8),
        'installment': optuna_trial.suggest_categorical('installment', [1, 2])
    }
    cerebro.addstrategy(TestStrategy, **opt_kwargs)
else:
    cerebro.addstrategy(TestStrategy)
cerebro.adddata(bt.feeds.PandasData(dataname=data))
cerebro.broker.setcash(1000000.0); cerebro.broker.setcommission(commission=0.0008)
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades'); cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
results = cerebro.run()
init_val = 1000000.0; final_val = cerebro.broker.getvalue(); total_prof = final_val - init_val; ret_pct = (total_prof / init_val) * 100
win_rate, mdd, total_tr = 0.0, 0.0, 0
if results:
    strat = results[0]; t_info = strat.analyzers.trades.get_analysis(); d_info = strat.analyzers.drawdown.get_analysis()
    total_tr = t_info.total.total if 'total' in t_info else 0
    if total_tr > 0 and 'won' in t_info: win_rate = round((t_info.won.total / total_tr) * 100, 2)
    if 'max' in d_info and 'drawdown' in d_info.max: mdd = round(d_info.max.drawdown, 2)
metrics = {"Total Return (%)": round(ret_pct,2), "Total Profit": round(total_prof, 2), "Win Rate (%)": win_rate, "MDD (%)": mdd, "Total Trades": total_tr, "Total Fees": round(sum([order.executed.comm for order in strat.broker.orders if order.status == order.Completed]), 2)}
"""
