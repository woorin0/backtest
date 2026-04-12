import pandas as pd
import io
import optuna

def create_excel_report(study, data_df):
    """Optuna Study의 상위 50개 전략 상세 지표를 포함한 전문 엑셀 리포트 생성"""
    
    # 1. 완료된 Trial들만 추출하여 수익률(value) 기준 내림차순 정렬
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    trials.sort(key=lambda t: t.value if t.value is not None else -9999, reverse=True)
    
    # 상위 50개 선정
    top_trials = trials[:50]
    
    report_rows = []
    for t in top_trials:
        # 기본 정보 (순위, 수익률)
        row = {
            "Rank": len(report_rows) + 1,
            "Total Return (%)": round(t.value, 2) if t.value is not None else 0.0
        }
        
        # 사용자 속성 (Win Rate, MDD, Trades 등)
        row.update({
            "Win Rate (%)": t.user_attrs.get("Win Rate (%)", 0.0),
            "MDD (%)": t.user_attrs.get("MDD (%)", 0.0),
            "Total Trades": t.user_attrs.get("Total Trades", 0),
            "Total Profit ($)": t.user_attrs.get("Total Profit", 0.0)
        })
        
        # 전략 파라미터 (Params)
        row.update(t.params)
        
        report_rows.append(row)
    
    # 데이터프레임 변환
    report_df = pd.DataFrame(report_rows)
    
    # 바이트 스트림으로 저장
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        report_df.to_excel(writer, sheet_name='Top_50_Strategies', index=False)
        
        # 엑셀 서식 자동 조정
        workbook  = writer.book
        worksheet = writer.sheets['Top_50_Strategies']
        
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
