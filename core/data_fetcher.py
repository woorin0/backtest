import ccxt
import pandas as pd
import streamlit as st
import time
import os
import hashlib

CACHE_DIR = "cache"

def get_timeframe_ms(timeframe):
    """주기(timeframe) 문자열을 밀리초(ms)로 변환"""
    unit = timeframe[-1]
    num = int(timeframe[:-1])
    if unit == 'm': return num * 60 * 1000
    if unit == 'h': return num * 60 * 60 * 1000
    if unit == 'd': return num * 24 * 60 * 60 * 1000
    if unit == 'w': return num * 7 * 24 * 60 * 60 * 1000
    return 60 * 60 * 1000 # 기본값 1시간

def get_cache_path(exchange_id, symbol, timeframe, start_date, end_date, padding_candles=250):
    """지정된 파라미터 조합에 대해 고유한 캐시 파일 경로를 생성 (패딩 정보 포함)"""
    key = f"{exchange_id}_{symbol}_{timeframe}_{start_date}_{end_date}_p{padding_candles}_v43"
    hash_key = hashlib.md5(key.encode()).hexdigest()
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    return os.path.join(CACHE_DIR, f"ohlcv_{hash_key}.pkl")

def fetch_candles(exchange_id: str, symbol: str, timeframe: str, start_date, end_date, limit: int, progress_bar=None, use_cache=True, padding_candles=250):
    """ccxt를 사용하여 지정된 기간 동안의 데이터를 수집 (지표 계산용 Warm-up 패딩 포함)"""
    
    # 캐시 확인
    cache_path = get_cache_path(exchange_id, symbol, timeframe, start_date, end_date, padding_candles=padding_candles)
    if use_cache and os.path.exists(cache_path):
        if progress_bar:
            progress_bar.progress(100, text=f"로컬 캐시에서 데이터를 불러왔습니다: {symbol}")
        try:
            return pd.read_pickle(cache_path)
        except Exception as e:
            print(f"캐시 읽기 에러 (재수집 시도): {e}")

    try:
        if progress_bar:
            progress_bar.progress(10, text="거래소 접속 중...")
            
        exchange_class = getattr(ccxt, exchange_id.lower())
        exchange = exchange_class({'timeout': 10000, 'enableRateLimit': True})
        
        # 🚨 [V4.3] 데이터 패딩 적용: 사용자가 선택한 시작일보다 과거로 거슬러 올라감
        tf_ms = get_timeframe_ms(timeframe)
        padding_ms = padding_candles * tf_ms
        base_since = int(pd.to_datetime(start_date).timestamp() * 1000)
        since = base_since - padding_ms
        
        end_timestamp = int(pd.to_datetime(end_date).timestamp() * 1000) + (24 * 60 * 60 * 1000) - 1
        
        all_ohlcv = []
        if progress_bar:
            progress_bar.progress(20, text=f"{exchange_id}에서 {symbol} 캔들 데이터 수집 시작 (Warm-up 포함)...")
            
        retry_count = 0
        while since < end_timestamp:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            except Exception as e:
                print(f"데이터 수신 지연 혹은 오류 발생: {e}")
                time.sleep(3); retry_count += 1
                if retry_count > 3: break
                continue
                
            if not ohlcv: break
            all_ohlcv.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]
            if last_timestamp >= end_timestamp: break
            if last_timestamp <= since: since += 1 
            else: since = last_timestamp + 1
            time.sleep(max(exchange.rateLimit / 1000, 0.1) if hasattr(exchange, 'rateLimit') else 0.5)
            
            if progress_bar:
                progress_bar.progress(min(int(len(all_ohlcv)/5000*100), 99), text=f"{len(all_ohlcv)}개 데이터 수집 중...")

        if not all_ohlcv: return None
            
        df = pd.DataFrame(all_ohlcv, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms')
        df.set_index('Datetime', inplace=True)
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        # 최종 필터링: 종료일까지만
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df.index <= end_dt]
        
        if use_cache: df.to_pickle(cache_path)
        if progress_bar: progress_bar.progress(100, text="데이터 수집 및 캐싱 완료")
            
        return df
    except Exception as e:
        print(f"데이터 수집 에러 발생: {e}")
        return None
