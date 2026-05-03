"""
🚀 [V8.0] Google Sheets 자동 전송 모듈 (Apps Script 웹훅 방식)
백테스트 완료 시 (엔진, 심볼, 주기) 조합별로 구글 시트 탭에 결과를 누적 전송합니다.
.env에 GOOGLE_SHEETS_WEBHOOK이 설정되어 있지 않으면 조용히 스킵합니다.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

def push_to_google_sheets(report_df, engine: str, symbol: str, timeframe: str):
    """
    백테스트 결과 DataFrame을 구글 시트에 전송합니다.
    
    Args:
        report_df: 엑셀에 저장되는 것과 동일한 DataFrame
        engine: 'Vectorbt' or 'Backtrader'
        symbol: 'BTC/USDT' 등
        timeframe: '1h', '15m' 등
    """
    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK", "")
    
    if not webhook_url or webhook_url.startswith("https://script.google.com") is False:
        if not webhook_url:
            return  # URL 미설정 → 조용히 스킵
    
    try:
        # (엔진, 심볼, 주기) 조합으로 시트 탭 이름 생성
        safe_symbol = symbol.replace("/", "-")
        sheet_name = f"{engine} {safe_symbol} {timeframe}"
        
        # DataFrame → 헤더 + 행 데이터로 변환
        headers = report_df.columns.tolist()
        # fillna(0.0)으로 NaN 값을 0.0으로 대체하고,
        # values.tolist()를 호출하면 numpy 타입도 파이썬 기본 타입으로 자동 변환되어 JSON 직렬화가 가능해집니다.
        rows = report_df.fillna(0.0).values.tolist()
        
        payload = {
            "sheet_name": sheet_name,
            "headers": headers,
            "rows": rows
        }
        
        # Apps Script 웹훅으로 POST 전송 (리다이렉트 따라가기 활성화)
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"},
            allow_redirects=True  # Apps Script는 리다이렉트를 사용함
        )
        
        if response.status_code == 200:
            print(f"[Google Sheets] ✅ '{sheet_name}' 탭에 {len(rows)}행 전송 완료")
        else:
            print(f"[Google Sheets] ⚠️ 응답 코드 {response.status_code}: {response.text[:200]}")
            
    except Exception as e:
        # 구글 시트 전송 실패는 백테스트 결과에 영향을 주지 않음
        print(f"[Google Sheets] ❌ 전송 실패 (무시됨): {str(e)}")
