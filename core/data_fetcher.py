import ccxt
import pandas as pd
import streamlit as st
import time
import os
import hashlib

CACHE_DIR = "cache"

def get_cache_path(exchange_id, symbol, timeframe, start_date, end_date):
    """지정된 파라미터 조합에 대해 고유한 캐시 파일 경로를 생성"""
    key = f"{exchange_id}_{symbol}_{timeframe}_{start_date}_{end_date}"
    # 파일명 안전성을 위해 해시값 사용 (특수문자 방지)
    hash_key = hashlib.md5(key.encode()).hexdigest()
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    return os.path.join(CACHE_DIR, f"ohlcv_{hash_key}.pkl")

def fetch_candles(exchange_id: str, symbol: str, timeframe: str, start_date, end_date, limit: int, progress_bar=None, use_cache=True):
    """ccxt를 사용하여 지정된 기간(start_date ~ end_date) 동안의 과거 캔들 데이터를 페이지네이션으로 모두 수집하는 함수 (캐싱 지원)"""
    
    # 캐시 확인
    cache_path = get_cache_path(exchange_id, symbol, timeframe, start_date, end_date)
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
        exchange = exchange_class({
            'timeout': 10000,
            'enableRateLimit': True,
        })
        
        since = int(pd.to_datetime(start_date).timestamp() * 1000)
        end_timestamp = int(pd.to_datetime(end_date).timestamp() * 1000) + (24 * 60 * 60 * 1000) - 1
        
        all_ohlcv = []
        
        if progress_bar:
            progress_bar.progress(20, text=f"{exchange_id}에서 {symbol} 캔들 데이터 수집 시작...")
            
        retry_count = 0
        while since < end_timestamp:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            except Exception as e:
                print(f"데이터 수신 지연 혹은 오류 발생: {e}")
                time.sleep(3)
                retry_count += 1
                if retry_count > 3:
                    break
                continue
                
            if not ohlcv:
                break
                
            all_ohlcv.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]
            
            if last_timestamp >= end_timestamp:
                break
                
            if last_timestamp <= since:
                since += 1 
            else:
                since = last_timestamp + 1
                
            time.sleep(max(exchange.rateLimit / 1000, 0.1) if hasattr(exchange, 'rateLimit') else 0.5)
            
            if progress_bar:
                progress_bar.progress(50, text=f"{len(all_ohlcv)}개 데이터 수집 중...")

        if not all_ohlcv:
            return None
            
        df = pd.DataFrame(all_ohlcv, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms')
        df.set_index('Datetime', inplace=True)
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df.index <= end_dt]
        
        # 캐시에 저장
        if use_cache:
            df.to_pickle(cache_path)
            
        if progress_bar:
            progress_bar.progress(100, text="데이터 수집 및 캐싱 완료")
            
        return df
    except Exception as e:
        print(f"데이터 수집 에러 발생: {e}")
        return None
