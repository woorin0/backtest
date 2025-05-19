import gspread
from oauth2client.service_account import ServiceAccountCredentials


results = []

# —— 중략 (기존 import 및 백테스트 코드) ——

# 구글 시트 연결 함수
def connect_sheet(creds_path: str, sheet_key: str, sheet_name: str):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_key)
    return sh.worksheet(sheet_name)

# 실행 시작 부분에 추가
SHEET_CRED_PATH = 'credentials.json'
SHEET_KEY       = 'YOUR_SPREADSHEET_ID'
SHEET_NAME      = 'Sheet1'  # 탭 이름

ws = connect_sheet(SHEET_CRED_PATH, SHEET_KEY, SHEET_NAME)

# 기존 백테스트 루프 후, CSV 저장 대신 아래로 대체
# df.to_csv("grid_backtest_results.csv", ...) 대신:

# 5) 시트에 헤더 한번 쓰기 (없으면)
try:
    if not ws.row_values(1):
        ws.append_row(['symbol','timeframe','mult','netProfit','winRate','maxDrawdown'])
except Exception:
    pass

# 6) 각 결과를 시트에 append
for rec in results:
    ws.append_row([
        rec['symbol'],
        rec['timeframe'],
        rec['mult'],
        rec['netProfit'],
        rec['winRate'],
        rec['maxDrawdown']
    ])

print("✅ Google Sheets에 모든 결과 기록 완료!")
