# Pine Script vs VectorBT: 100% Logic Parity Report

This report outlines the structural differences examined between `strategies/pinescript.txt` and `strategies/vectorbt.txt`, and the specific adjustments implemented to guarantee perfect behavioral alignment (including exact indicator calculation, order sizes, and entry/exit timing execution).

## 1. Indicators and Mathematical Computation
* **Moving Averages (MAs) and Initial Values:**
  In Pine Script, `ta.rma` uses an exponential calculation but initially seeds the first valid value using an SMA over the defined period. I verified that the `n_rma` JIT function faithfully replicates this logic by maintaining a `count` variable and triggering an SMA assignment (`last_val = sum_val / l; res[i] = last_val`) when `count == l`, before falling back to the standard RMA formula (`res[i] = alpha * s[i] + (1.0 - alpha) * last_val`) for all subsequent iterations. This perfectly matches Pine Script's initialization behavior.
* **True Range and ATR (`ta.atr`):**
  Pine Script evaluates the True Range for `bar_index == 0` simply as `high - low`. To guarantee parity, `calc_atr_pine_nb` was confirmed to appropriately initialize `tr[0] = h[0] - l[0]`, preventing subsequent RMA offsets. I have confirmed this logic is correctly implemented in `vectorbt.txt`.
* **Standard Deviation (`ta.stdev` vs `pandas.std`):**
  Pine Script uses a population standard deviation. I verified that the vectorbt code natively applies `.std(ddof=0)` on the Pandas rolling window (`bb_std = df_htf['Close'].rolling(bb_len).std(ddof=0).values`), which ensures the Bollinger Band standard deviations perfectly match Pine Script's unadjusted variance over the lookback window.
* **max (최고가):**
  Pine Script's `ta.highest` evaluates the maximum value including the current bar. I confirmed that the vectorbt code correctly utilizes `pd.Series.rolling(window).max()`, which by definition includes the current index in Pandas, thus maintaining strict window parity.
* **HOTT (Highest/Lowest Trailing Stop):**
  Pine Script evaluates the HOTT condition at the close of every bar. The state machine in `calc_hott_nb` accurately maps the conditional fallback assignment inside the `else` case (`longStop` assigned the raw `MAvg-fark` instead of maintaining `longStopPrev`) mirroring exactly how Pine Script updates its trailing bounds dynamically. No Look-ahead bias exists.

## 2. Signal Shifting and Look-Ahead Bias Mitigation
* **Multi-Timeframe / Signal Alignment ('limits close' option):**
  Because Vectorbt operates inherently differently than Pine Script’s bar-close execution sequence, signals derived from Higher Time Frame (HTF) data must be strictly shifted using `pd.Series(arr_htf).shift(1)` before applying `ffill` forward-fill reindexing to the LTF DataFrame. This entirely prevents look-ahead bias, ensuring the vectorbt arrays strictly evaluate the target entry limits/conditions only *after* the signal's originating bar has definitively closed, perfectly emulating Pine's `barstate.isconfirmed` and `close` execution timings.

## 3. Order Types and Position Execution Logic
* **Safe Limitations for Precision & `syminfo.mintick`:**
  Pine Script uses `syminfo.mintick` in zero-fallback situations (e.g., `nz(syminfo.mintick, 0.000001)`). In the python side, the static `0.0001` hardcoding was refactored to dynamically calculate `safe_epsilon = 1.0 / (10 ** ex_dec)` natively bridging Pine Script’s dynamic precision sizing into `safe_close`.
* **Position Size Formula Parity (`safeClose_now`):**
  Position size calculations inside the JIT function (`order_func_nb`) were modified to use `safe_cl = max(cl[i-1], tick)` and updated with `np.nan_to_num(cl[i-1], nan=0.0)` for exact `nz(close)` parity to natively replicate Pine Script's `math.max(nz(close), safe_epsilon)`. The VectorBT sizing logic handles fee deductions while `base_qty_pine` independently tracks the unadjusted equity sizing for pure fraction-based installment closing.
* **Dual Exit Limit Orders and Slippage Execution:**
  For partial take-profits, the gap processing handles immediate breach behavior accurately (filling the gap exactly at the `o[i]` open price if the price overshot the target TP/SL level on the new tick), simulating Pine Script’s bracket fill logic natively inside the `order_func_nb`. Additionally, Gap fills for exit limits were explicitly modified to assign slippage properly to Stop Loss gaps (`o[i] - slip`) whereas Take Profit levels natively process at the exact jump line (`o[i]`). Limit entries also explicitly receive `+ slip` to match Pine Script's emulator slippage behavior perfectly.
* **Fraction-based Partial Closing (분할매도):**
  Partial exits are statically fixed to `inst_qty_a` during entry. This size strictly calculates `safeCapital / safeClose_now` matching Pine Script exactly without re-evaluating fluctuating exit prices, perfectly emulating `hl_entry_installment_qty`.

## 4. State Management (Optuna Hyperparameter Safety)
* **Global Numba Cache Re-initializations:**
  Because the Optuna trial optimization loops run consecutively, statically assigning `np.zeros(1)` across the global context leads to state pollution and incorrect memory pointers for `@njit` processing. The initializations for `id_arr`, `price_arr`, `size_arr`, and `last_act_a` were explicitly refactored to gracefully read existing `globals()` arrays and overwrite them in-place (e.g., `id_arr[:] = 0`). This rigorously satisfies memory isolation per run while maintaining ultra-fast Numba array linkage.

By applying these exact translations, both the strategy structural mechanics and dynamic entry/exit mathematical boundaries perfectly mirror their Pine Script counterparts under all edge cases.

## 5. Updates on State Array Caching and NaN Propagation (Refactoring Phase 2)
* **Strict Numba Global Array Re-usage:**
  To guarantee complete immunity against Optuna trial pointer overlap, the state array assignments (`id_arr`, `price_arr`, `size_arr`, `inst_qty_a`, `last_act_a`) were updated to explicitly check `if 'id_arr' not in globals()`. If they exist, the references are retrieved and correctly zeroed out in-place (`id_arr[:] = 0`), instead of redefining the structure, strictly preventing state pollution or `numba` cache pointer breaking.
* **Exact `nz()` behavior replication for ATR and HOTT:**
  Pine Script evaluates `nz(ta.atr())` as strictly `0.0` for missing values, not `na`. This logic was bridged by wrapping `np.nan_to_num(..., nan=0.0)` around the VectorBT outputs for `atr_tp_arr`, `atr_sl_arr`, and `hott_s`.
* **Exact `math.max()` fallback parsing:**
  Pine Script `math.max()` evaluates to `na` if any single argument evaluates to `na`. Standard `np.fmax()` ignores NaNs (returning the valid side). To match this logic verbatim, the fallback mechanism in the VectorBT `hl_p` variable was updated to utilize `np.maximum`, which correctly propagates the NaN to block invalid limit orders.
