import pandas as pd
import io
import optuna

# 🚀 [V7.5] 트레이딩뷰 설정창 UI 순서와 완벽히 동기화된 컬럼 정렬 순서
PINE_ORDER = [
    # === 기본 성과 지표 ===
    "Rank", "Total Return (%)", "Win Rate (%)", "MDD (%)", "Total Trades", "Total Profit ($)", "Total Fees ($)",
    # === BASIC CONDITION ===
    "hl_price", "open_at_hl", "open_at_ll", "exit_at_hl", "exit_at_ll",
    "hl_tp_price", "hl_sl_price", "tr_hl",
    # === LL MOVING AVERAGE ===
    "ll_volatility_filter", "ma1_len", "ll_mult", "ma2_type", "ma2_len",
    # === HL BOLLINGER BANDS ===
    "bb_ma_type", "bb_length", "bb_dev", "bb_min_width",
    # === HL H/L OTT ===
    "hott_length", "hott_percent", "hott_h_length", "hott_ma_type", "hott_h_src", "high_int",
    # === PERCENTAGE ===
    "entry_ll_per", "tp_hl_per", "tp_ll_per", "sl_hl_per", "sl_ll_per",
    # === ATR ===
    "atr_length", "hl_tp_atr_mul", "atr_length2", "hl_sl_atr_mul",
    # === TR ===
    "tr_ma_type", "tr_ma_len",
    # === SIZE ===
    "exchange_decimal", "installment",
]

def create_report_dataframe(study):
    """🚀 [V8.0] Optuna Study에서 상위 100개 전략의 DataFrame을 생성하는 공용 함수.
    엑셀 리포트와 구글 시트 전송 모듈이 함께 사용합니다."""
    
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    top_trials = trials[:100]
    
    report_rows = []
    for t in top_trials:
        row = {
            "Rank": len(report_rows) + 1,
            "Total Return (%)": round(t.value, 2) if t.value is not None else 0.0,
            "Win Rate (%)": t.user_attrs.get("Win Rate (%)", 0.0),
            "MDD (%)": t.user_attrs.get("MDD (%)", 0.0),
            "Total Trades": t.user_attrs.get("Total Trades", 0),
            "Total Profit ($)": t.user_attrs.get("Total Profit", 0.0),
            "Total Fees ($)": round(t.user_attrs.get("Total Fees", 0.0), 2)
        }
        row.update(t.params)
        report_rows.append(row)
    
    report_df = pd.DataFrame(report_rows)
    
    # 컬럼 순서 정렬 (트레이딩뷰 UI 순서)
    final_columns = [col for col in PINE_ORDER if col in report_df.columns]
    remaining_columns = [col for col in report_df.columns if col not in PINE_ORDER]
    report_df = report_df[final_columns + remaining_columns]
    
    return report_df

def create_excel_report(study, data_df):
    """Optuna Study의 상위 100개 전략 상세 지표를 포함한 전문 엑셀 리포트 생성"""
    
    report_df = create_report_dataframe(study)
    
    # 4. 바이트 스트림으로 저장
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        report_df.to_excel(writer, sheet_name='Top_100_Strategies', index=False)
        
        # 엑셀 서식 자동 조정
        workbook  = writer.book
        worksheet = writer.sheets['Top_100_Strategies']
        
        # 헤더 서식
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#D7E4BC',
            'border': 1
        })
        
        for col_num, value in enumerate(report_df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            column_len = max(report_df[value].astype(str).map(len).max(), len(value)) + 2
            worksheet.set_column(col_num, col_num, column_len)
            
    output.seek(0)
    return output

# 기존 함수 유지 (호환성용)
def create_excel_buffer(data, results):
    # 이 함수는 이제 사용되지 않거나 리팩토링 대상입니다.
    # 새로운 create_excel_report를 사용하도록 tasks.py를 수정할 것입니다.
    output = io.BytesIO()
    pd.DataFrame(results).to_excel(output, index=False)
    output.seek(0)
    return output
