import pandas as pd
import io
import optuna

def create_excel_report(study, data_df):
    """Optuna Study의 상위 100개 전략 상세 지표를 포함한 전문 엑셀 리포트 생성"""
    
    # 1. 완료된 Trial들만 추출하여 수익률(value) 기준 내림차순 정렬
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    
    # 상위 100개 선정
    top_trials = trials[:100]
    
    # 2. 리포트 데이터 생성
    report_rows = []
    for t in top_trials:
        # 기본 정보 (Rank 및 핵심 지표)
        row = {
            "Rank": len(report_rows) + 1,
            "Total Return (%)": round(t.value, 2) if t.value is not None else 0.0,
            "Win Rate (%)": t.user_attrs.get("Win Rate (%)", 0.0),
            "MDD (%)": t.user_attrs.get("MDD (%)", 0.0),
            "Total Trades": t.user_attrs.get("Total Trades", 0),
            "Total Profit ($)": t.user_attrs.get("Total Profit", 0.0),
            "Total Fees ($)": round(t.user_attrs.get("Total Fees", 0.0), 2)
        }
        
        # 전략 파라미터 (Params)
        row.update(t.params)
        report_rows.append(row)
    
    # 3. 데이터프레임 변환 및 컬럼 순서 재배치 (Pine Script 순서 동기화)
    report_df = pd.DataFrame(report_rows)
    
    # 파인스크립트 소스코드와 동일한 논리적 정렬 순서 정의
    PINE_ORDER = [
        "Rank", "Total Return (%)", "Win Rate (%)", "MDD (%)", "Total Trades", "Total Profit ($)", "Total Fees ($)", # 기본 지표
        "hl_price", "bb_ma_type", "bb_length", "bb_dev", "bb_min_width",       # Indicator Group 1
        "hott_ma_type", "hott_length", "hott_percent", "hott_h_length", "hott_h_src", "high_int", # Indicator Group 2
        "hl_tp_atr_mul", "hl_sl_atr_mul", "open_at_hl", "open_at_ll",           # Strategy Group 1
        "exit_at_hl", "exit_at_ll", "hl_tp_price", "hl_sl_price",               # Strategy Group 2
        "ma2_type", "ma2_len", "ma1_len", "tr_ma_type", "tr_ma_len",            # MA Group
        "atr_length", "atr_length2", "ll_mult", "ll_volatility_filter",         # ATR/Filter Group
        "entry_ll_per", "tp_hl_per", "sl_hl_per", "tp_ll_per", "sl_ll_per",     # Trigger Group
        "exchange_decimal", "installment", "tr_hl"                             # System Group
    ]
    
    # 존재하는 컬럼만 필터링하여 순서 적용 (엔진별 파라미터 차이 대응)
    final_columns = [col for col in PINE_ORDER if col in report_df.columns]
    # 명시되지 않은 나머지 컬럼이 있다면 뒤에 붙임
    remaining_columns = [col for col in report_df.columns if col not in PINE_ORDER]
    report_df = report_df[final_columns + remaining_columns]
    
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
