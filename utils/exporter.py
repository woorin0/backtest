import pandas as pd
import io

def create_excel_buffer(data: pd.DataFrame, metrics: dict):
    """결과 DataFrame과 Metrics 딕셔너리를 in-memory bytes array로 패키징"""
    output = io.BytesIO()
    
    metrics_df = pd.DataFrame(metrics.items(), columns=["Metric", "Value"])
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        metrics_df.to_excel(writer, sheet_name='Summary', index=False)
        data.to_excel(writer, sheet_name='Price Data')
    
    output.seek(0)
    return output
