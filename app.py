import streamlit as st
import os
import datetime
from dotenv import load_dotenv

# 내부 모듈 임포트
from core.data_fetcher import fetch_candles
from core.engine_runner import run_backtest
from core.notifier import send_discord_alert
from utils.exporter import create_excel_buffer

# 환경 변수 로드
load_dotenv()

st.set_page_config(page_title="Quant Backtest Dashboard", layout="wide")

# CSS 커스텀 스타일 (간단한 색상 지정)
st.markdown("""
<style>
div.stButton > button:first-child {
    background-color: #4CAF50;
    color: white;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 웹 기반 퀀트 백테스트 대시보드")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ 설정 항목")
    exchange = st.selectbox("거래소", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"])
    symbol = st.text_input("종목 쌍", value="BTC/USDT")
    engine = st.selectbox("백테스트 엔진", ["Backtrader", "Vectorbt"])
    
    st.markdown("---")
    st.subheader("📅 타임프레임 및 기간 설정")
    # 사용자가 직접 입력 가능하게 변경 (selectbox -> text_input)
    timeframe = st.text_input("타임프레임 (예: 1d, 4h, 1h, 15m, 5m, 1m)", value="1h")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("시작일", value=datetime.date.today() - datetime.timedelta(days=30))
    with col_d2:
        end_date = st.date_input("종료일", value=datetime.date.today())
        
    limit = st.number_input("1회 요청 최대 갯수", min_value=100, max_value=5000, value=1000, step=100)
    
    start_btn = st.button("🚀 백테스트 시작", use_container_width=True)

with col2:
    st.subheader("💻 전략 코드 입력")
    
    # 템플릿 코드 분기
    if engine == "Backtrader":
        default_code = """# Backtrader 엔진용 전략 클래스 템플릿입니다.
# 반드시 'TestStrategy'라는 이름의 클래스를 정의하고 bt.Strategy를 상속받아야 합니다.
import backtrader as bt

class TestStrategy(bt.Strategy):
    params = (
        ('sma_period', 15),
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.sma = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.sma_period)

    def next(self):
        if not self.position:
            if self.dataclose[0] > self.sma[0]:
                self.buy()
        else:
            if self.dataclose[0] < self.sma[0]:
                self.sell()
"""
    else:
        default_code = """# Vectorbt 엔진용 전략 스크립트 템플릿입니다.
# 'data' 변수(Pandas DataFrame)가 런타임에 주입됩니다.
import vectorbt as vbt
import pandas as pd

close = data['Close']

# 이동평균 계산 및 신호 생성
fast_ma = vbt.MA.run(close, 10, short_name='fast')
slow_ma = vbt.MA.run(close, 50, short_name='slow')

entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

# 포트폴리오 백테스트
portfolio = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10000)

# 결과 메트릭 추출 (필수 변수: metrics)
metrics = {
    "Total Return (%)": round(portfolio.total_return() * 100, 2) if hasattr(portfolio, 'total_return') else 0,
    "Win Rate (%)": round(portfolio.win_rate() * 100, 2) if hasattr(portfolio, 'win_rate') else 0,
    "Max Drawdown (%)": round(portfolio.max_drawdown() * 100, 2) if hasattr(portfolio, 'max_drawdown') else 0,
    "Total Trades": portfolio.trades.count() if hasattr(portfolio, 'trades') else 0
}
"""
    
    strategy_code = st.text_area("파이썬 코드를 작성하세요", value=default_code, height=450)

st.markdown("---")

# 실행 및 결과 처리 플로우
if start_btn:
    st.subheader("🔄 실행 진행 현황")
    
    # 0~100% 게이지바
    prog_bar = st.progress(0, text="백테스트 준비 중...")
    
    # 1. 과거 캔들 데이터 구간 반복 연동 수집
    data = fetch_candles(exchange, symbol, timeframe, start_date, end_date, limit, prog_bar)
    
    if data is not None and not data.empty:
        # 2. 백테스트 엔진 구동
        with st.spinner(f"[{engine}] 백테스트 계산 중..."):
            success, result_or_err = run_backtest(engine, strategy_code, data)
            prog_bar.progress(90, text="백테스트 연산 완료, 결과 처리 중...")
            
            if success:
                metrics = result_or_err
                st.success("🎉 백테스트가 완료되었습니다!")
                
                # 요약 결과 메트릭 생성
                st.write("**요약 성과 지표**")
                cols = st.columns(len(metrics))
                for i, (k, v) in enumerate(metrics.items()):
                    cols[i].metric(label=k, value=v)
                
                # 데이터 프레임 렌더링
                st.write("**최근 시세 기록 (10 rows)**")
                st.dataframe(data.tail(10))
                
                # 3. 엑셀 변환 로직 연동
                excel_buffer = create_excel_buffer(data, metrics)
                
                col_dl, col_wh = st.columns(2)
                
                # 다운로드 버튼
                with col_dl:
                    st.download_button(
                        label="📥 엑셀 결과 다운로드 (.xlsx)",
                        data=excel_buffer,
                        file_name=f"Backtest_{exchange}_{symbol.replace('/','-')}_{engine}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                
                # 4. 웹훅 전송
                wh_success, wh_msg = send_discord_alert(metrics, engine, symbol)
                with col_wh:
                    if wh_success:
                        st.info("🔔 디스코드 웹훅 알림 발송 성공")
                    else:
                        st.warning(f"🔕 웹훅 알림 발송 실패: {wh_msg}")
                
                prog_bar.progress(100, text="모든 작업이 무사히 완료되었습니다!")
            else:
                st.error(f"스크립트 에러: {result_or_err}")
                prog_bar.empty()
    else:
        st.error("데이터 다운로드에 실패했습니다. (거래소 또는 심볼 이름 확인)")
        prog_bar.empty()
