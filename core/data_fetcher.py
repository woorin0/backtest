import ccxt
import pandas as pd
import streamlit as st

def fetch_candles(exchange_id: str, symbol: str, timeframe: str, limit: int, progress_bar=None):
    """ccxt를 사용하여 과거 캔들 데이터를 수집하는 함수"""
    try:
        if progress_bar:
            progress_bar.progress(10, text="거래소 접속 중...")
            
        # ccxt 거래소 객체 동적 생성
        exchange_class = getattr(ccxt, exchange_id.lower())
        exchange = exchange_class()
        
        # 데이터 다운로드 API 요청
        if progress_bar:
            progress_bar.progress(40, text=f"{exchange_id}에서 {symbol} 캔들 데이터 수신 중...")
            
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        if progress_bar:
            progress_bar.progress(60, text="수신된 데이터 Pandas DataFrame 변환 중...")
            
        # DataFrame 파싱
        df = pd.DataFrame(ohlcv, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        # 밀리초 유닉스타임을 datetime 객체로 변환
        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms')
        df.set_index('Datetime', inplace=True)
        
        if progress_bar:
            progress_bar.progress(80, text="데이터 수집 완료 (엔진 준비 중...)")
            
        return df
    except Exception as e:
        return None
