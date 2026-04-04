import streamlit as st
import os
import datetime
from dotenv import load_dotenv

import time
import optuna
from optuna.storages import RDBStorage
from celery.result import AsyncResult

from core.tasks import run_optimization_task

# 환경 변수 로드
load_dotenv()

st.set_page_config(page_title="Quant Backtest Dashboard", layout="wide")

# CSS 커스텀 스타일
st.markdown("""
<style>
div.stButton > button:first-child {
    background-color: #4CAF50;
    color: white;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 웹 기반 퀀트 최적화 대시보드 (비동기 처리)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ 설정 항목")
    exchange = st.selectbox("거래소", ["Binance", "Bitget", "Bybit", "OKX", "Upbit"])
    symbol = st.text_input("종목 쌍", value="BTC/USDT")
    engine = st.selectbox("백테스트 엔진", ["Backtrader", "Vectorbt"])
    
    st.markdown("---")
    st.subheader("📅 타임프레임 및 최적화 설정")
    timeframe = st.text_input("타임프레임 (예: 1d, 4h, 1h, 15m, 5m, 1m)", value="1h")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("시작일", value=datetime.date.today() - datetime.timedelta(days=30))
    with col_d2:
        end_date = st.date_input("종료일", value=datetime.date.today())
        
    limit = st.number_input("1회 요청 최대 갯수", min_value=100, max_value=5000, value=1000, step=100)
    n_trials = st.number_input("Optuna 최적화 반복 탐색 횟수", min_value=10, max_value=10000, value=100, step=50)
    
    start_btn = st.button("🚀 백테스트 최적화 시작", use_container_width=True)

with col2:
    st.subheader("💻 전략 코드 입력")
    
    if engine == "Backtrader":
        default_code = """# Backtrader 엔진용 전략 클래스 템플릿입니다.
# 반드시 'TestStrategy'라는 이름의 클래스를 정의하고 bt.Strategy를 상속받아야 합니다.
# 'optuna_trial' 객체가 백그라운드 워커에서 주입됩니다.
import backtrader as bt

class TestStrategy(bt.Strategy):
    params = (
        ('sma_period', optuna_trial.suggest_int('sma_period', 5, 50) if 'optuna_trial' in globals() and optuna_trial else 15),
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
# 'data' 변수와 'optuna_trial' 변수가 런타임에 주입됩니다.
import vectorbt as vbt
import pandas as pd

close = data['Close']

# Optuna 파라미터 최적화 (fast는 5~20 튜닝, slow는 30~100 사이 튜닝)
if optuna_trial:
    fast_period = optuna_trial.suggest_int('fast', 5, 20)
    slow_period = optuna_trial.suggest_int('slow', 30, 100)
else:
    fast_period = 10
    slow_period = 50

# 이동평균 계산 및 신호 생성
fast_ma = vbt.MA.run(close, fast_period, short_name='fast')
slow_ma = vbt.MA.run(close, slow_period, short_name='slow')

entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

# 포트폴리오 백테스트
portfolio = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10000)

# 결과 메트릭 추출
metrics = {
    "Total Return (%)": round(portfolio.total_return() * 100, 2) if hasattr(portfolio, 'total_return') else 0,
    "Win Rate (%)": round(portfolio.win_rate() * 100, 2) if hasattr(portfolio, 'win_rate') else 0,
    "Max Drawdown (%)": round(portfolio.max_drawdown() * 100, 2) if hasattr(portfolio, 'max_drawdown') else 0,
    "Total Trades": portfolio.trades.count() if hasattr(portfolio, 'trades') else 0
}
"""
    
    strategy_code = st.text_area("파이썬 코드를 작성하세요", value=default_code, height=450)

st.markdown("---")

# 실행 및 결과 처리 플로우 (비동기 방식)
if start_btn:
    st.subheader("🔄 최적화 실행 진행 현황")
    
    # Celery Task Trigger
    task = run_optimization_task.apply_async(kwargs={
        'exchange': exchange,
        'symbol': symbol,
        'timeframe': timeframe,
        'start_date': str(start_date),
        'end_date': str(end_date),
        'limit': limit,
        'engine': engine,
        'code_str': strategy_code,
        'n_trials': n_trials
    })
    
    st.info(f"🚀 Celery 백그라운드 워커에 최적화 작업을 넘겼습니다. (Task ID: {task.id})")
    
    status_placeholder = st.empty()
    gauge_placeholder = st.empty()
    
    study_name = f"study_{task.id}"
    storage = RDBStorage("sqlite:///optuna_study.db")
    
    with st.spinner("Celery 큐 대기 및 최적화 진행 중... 실시간 지표 폴링"):
        while True:
            # Task 상태 체크
            if task.ready():
                break
            
            # SQLite Optuna Study DB 읽어서 진행상황 렌더링
            try:
                study = optuna.load_study(study_name=study_name, storage=storage)
                trials = study.trials
                completed = len([t for t in trials if t.state == optuna.trial.TrialState.COMPLETE])
                
                # 시상 최고 수익률 추적
                best_val = study.best_value if completed > 0 else 0
                
                prog = min(int(completed / n_trials * 100), 100)
                gauge_placeholder.progress(prog, text=f"완료 횟수: {completed} / {n_trials}")
                status_placeholder.markdown(f"### 🔥 현재 찾아낸 최고 수익률: **{best_val:.2f}%**")
                
            except Exception as e:
                status_placeholder.markdown("Optuna Study 초기화 대기 중...")
            
            time.sleep(1.5)
            
    # 최종 결과 반환
    final_res = task.get()
    
    if isinstance(final_res, dict) and final_res.get('status') == 'SUCCESS':
        gauge_placeholder.progress(100, text="최적화 완전 종료")
        st.success(f"🎉 완료되었습니다! 최종 최고 수익률: **{final_res.get('best_value'):.2f}%**")
        st.info("🔔 디스코드 웹훅으로 최적화 완료 알림이 전송되었습니다. (Top 30 상세 상세 내역은 아래 엑셀에 포함)")
        
        # 엑셀 다운로드 버튼 활성화
        excel_path = final_res.get('excel_file')
        if excel_path and os.path.exists(excel_path):
            with open(excel_path, "rb") as f:
                st.download_button(
                    label="📥 최고 성과 1위 상세 데이터 및 Top 30 랭킹 엑셀 다운로드 (.xlsx)",
                    data=f,
                    file_name=f"Best_Backtest_{exchange}_{symbol.replace('/','-')}_{engine}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    else:
        gauge_placeholder.empty()
        st.error(f"작업 실패 또는 에러 발생: {final_res}")
