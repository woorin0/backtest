import ccxt
import pandas as pd
import streamlit as st
import time

def fetch_candles(exchange_id: str, symbol: str, timeframe: str, start_date, end_date, limit: int, progress_bar=None):
    """ccxt를 사용하여 지정된 기간(start_date ~ end_date) 동안의 과거 캔들 데이터를 페이지네이션으로 모두 수집하는 함수"""
    try:
        if progress_bar:
            progress_bar.progress(10, text="거래소 접속 중...")
            
        exchange_class = getattr(ccxt, exchange_id.lower())
        exchange = exchange_class()
        
        # 날짜를 파싱 후 ccxt가 요구하는 밀리초(ms) 단위 timestamp로 변환
        since = int(pd.to_datetime(start_date).timestamp() * 1000)
        
        # 자정까지의 데이터를 온전히 포함하기 위해 하루 치 시간을 추가
        end_timestamp = int(pd.to_datetime(end_date).timestamp() * 1000) + (24 * 60 * 60 * 1000) - 1
        
        all_ohlcv = []
        
        if progress_bar:
            progress_bar.progress(20, text=f"{exchange_id}에서 {symbol} 캔들 데이터 페이지네이션 수신 시작...")
            
        while since < end_timestamp:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            except Exception as e:
                st.warning(f"데이터 수신 지연 혹은 오류 발생: {e}")
                time.sleep(1)
                continue
                
            if not ohlcv:
                break
                
            all_ohlcv.extend(ohlcv)
            
            last_timestamp = ohlcv[-1][0]
            
            # 수집된 최신 데이터가 종료일을 넘어섰다면 조기 종료
            if last_timestamp >= end_timestamp:
                break
                
            # 무한 루프 방지
            if last_timestamp <= since:
                since += 1 
            else:
                since = last_timestamp + 1
                
            # 거래소 Rate Limit (API 호출 빈도 제한) 준수를 위한 딜레이
            time.sleep(max(exchange.rateLimit / 1000, 0.1) if hasattr(exchange, 'rateLimit') else 0.5)
            
            if progress_bar:
                progress_bar.progress(50, text=f"{len(all_ohlcv)}개 데이터 수집 연장 중 (Time: {pd.to_datetime(last_timestamp, unit='ms')})...")

        if not all_ohlcv:
            return None
            
        if progress_bar:
            progress_bar.progress(70, text="수신된 전체 데이터 DataFrame 변환 중...")
            
        # DataFrame 파싱
        df = pd.DataFrame(all_ohlcv, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms')
        df.set_index('Datetime', inplace=True)
        
        # 페이지네이션 겹침으로 인한 중복 제거 및 시간 순 정렬
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        # 사용자가 요청한 딱 그날까지만 남기도록 꼬리 자르기
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df.index <= end_dt]
        
        if progress_bar:
            progress_bar.progress(80, text="데이터 수집 및 병합 완전 종료")
            
        return df
    except Exception as e:
        st.error(f"데이터 수집 에러 발생: {e}")
        return None
