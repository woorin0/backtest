import pandas as pd
import io

def create_excel_buffer(data: pd.DataFrame, top_configs: list = None):
    """결과 DataFrame과 Top50을 in-memory bytes array로 패키징"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if top_configs:
            top_df = pd.DataFrame(top_configs)
            if 'params' in top_df.columns:
                top_df['params'] = top_df['params'].astype(str)
            top_df.insert(0, 'Rank', range(1, len(top_df) + 1))
            top_df.to_excel(writer, sheet_name='Top 50 Results', index=False)
            
        data.to_excel(writer, sheet_name='Price Data')
    
    output.seek(0)
    return output
