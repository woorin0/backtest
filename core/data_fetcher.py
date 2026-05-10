import ccxt
import pandas as pd
import streamlit as st
import time
import os
import hashlib
import redis

# Redis 연결 (기존 db=2 사용)
status_redis = redis.Redis(host='localhost', port=6379, db=2, decode_responses=True)

class RedisProgress:
    """Streamlit의 progress_bar와 동일한 인터페이스를 가지며 Redis에 진행 상황을 기록"""
    def __init__(self, key):
        self.key = key
    def progress(self, value, text=""):
        status_redis.set(self.key, f"📊 {text} ({value}%)", ex=600)
    def empty(self):
        status_redis.delete(self.key)

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
    return os.path.join(CACHE_DIR, f"ohlcv_{hash_key}.parquet")

# 🚀 [V10.0] 거래소별 지원 타임프레임 (Upbit은 2h 미지원)
EXCHANGE_TIMEFRAMES = {
    'binance': ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '1w'],
    'upbit':   ['1m', '3m', '5m', '10m', '15m', '30m', '1h', '4h', '1d', '1w'],
}

def validate_timeframe(exchange_id: str, timeframe: str):
    """거래소가 해당 타임프레임을 지원하는지 확인하고, 미지원 시 대체 타임프레임을 반환"""
    ex_lower = exchange_id.lower()
    supported = EXCHANGE_TIMEFRAMES.get(ex_lower, [])
    if not supported or timeframe in supported:
        return timeframe  # 지원하거나 알 수 없는 거래소면 그대로 사용
    
    # 미지원 타임프레임 → 가장 가까운 상위 타임프레임으로 대체
    tf_ms = get_timeframe_ms(timeframe)
    best = None
    for s_tf in supported:
        s_ms = get_timeframe_ms(s_tf)
        if s_ms >= tf_ms:
            if best is None or s_ms < get_timeframe_ms(best):
                best = s_tf
    fallback = best if best else supported[-1]
    print(f"[Warning] {exchange_id}는 '{timeframe}' 미지원 -> '{fallback}'로 대체합니다.")
    return fallback

def fetch_candles(exchange_id: str, symbol: str, timeframe: str, start_date, end_date, limit: int, progress_bar=None, use_cache=True, padding_candles=250):
    """ccxt를 사용하여 지정된 기간 동안의 데이터를 수집 (지표 계산용 Warm-up 패딩 포함)"""
    
    # 🚀 [V10.0] 거래소별 타임프레임 호환성 검증
    timeframe = validate_timeframe(exchange_id, timeframe)
    
    # 캐시 확인
    cache_path = get_cache_path(exchange_id, symbol, timeframe, start_date, end_date, padding_candles=padding_candles)
    if use_cache and os.path.exists(cache_path):
        if progress_bar:
            progress_bar.progress(100, text=f"로컬 캐시에서 데이터를 불러왔습니다: {symbol}")
        try:
            return pd.read_parquet(cache_path)
        except Exception as e:
            print(f"캐시 읽기 에러 (재수집 시도): {e}")

    try:
        if progress_bar:
            progress_bar.progress(10, text=f"{exchange_id} 거래소 접속 중...")
            
        exchange_class = getattr(ccxt, exchange_id.lower())
        exchange = exchange_class({'timeout': 30000, 'enableRateLimit': True})
        
        # 🚀 [V10.0] 마켓 정보 사전 로드 (Upbit 등 일부 거래소에서 필수)
        exchange.load_markets()
        
        # 🚀 [V10.0] 심볼 존재 여부 사전 검증
        if symbol not in exchange.markets:
            raise Exception(f"'{exchange_id}' 거래소에서 '{symbol}' 심볼을 찾을 수 없습니다. (사용 가능 예시: {list(exchange.markets.keys())[:5]})")
        
        # 🚨 [V4.3] 데이터 패딩 적용: 사용자가 선택한 시작일보다 과거로 거슬러 올라감
        tf_ms = get_timeframe_ms(timeframe)
        padding_ms = padding_candles * tf_ms
        base_since = int(pd.to_datetime(start_date).timestamp() * 1000)
        since = base_since - padding_ms
        
        end_timestamp = int(pd.to_datetime(end_date).timestamp() * 1000) + (24 * 60 * 60 * 1000) - 1
        
        # 🚀 [V19] 정확한 다운로드 진행률 표기를 위해 전체 예상 캔들 수 계산
        total_expected = max((end_timestamp - since) / tf_ms, 1)
        
        # 🚀 [V10.0] Upbit API 제한: 한 번에 최대 200개만 가져올 수 있음
        ex_lower = exchange_id.lower()
        if ex_lower == 'upbit':
            limit = min(limit, 200)
        
        all_ohlcv = []
        if progress_bar:
            progress_bar.progress(20, text=f"{exchange_id}에서 {symbol} ({timeframe}) 캔들 데이터 수집 시작 (Warm-up 포함)...")
            
        retry_count = 0
        consecutive_empty = 0  # 🚀 [V10.0] 연속 빈 응답 카운터

        # 🚨 [Bugfix] 연속 빈 응답 허용치를 패딩 기간 + 여유분(최대 10초 스캔 분량, 약 50번 점프)으로 동적 계산하여 조기 종료 방지
        safe_limit = max(limit, 1)
        max_empty_jumps = max(3, int(padding_candles / safe_limit) + 50)

        while since < end_timestamp:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            except Exception as e:
                print(f"데이터 수신 지연 혹은 오류 발생: {e}")
                time.sleep(3); retry_count += 1
                if retry_count > 5: break  # 🚀 [V10.0] 재시도 횟수 5회로 확대
                continue
            
            if not ohlcv:
                consecutive_empty += 1
                if consecutive_empty > max_empty_jumps:
                    print(f"[Warning] 연속 빈 응답 {consecutive_empty}회 -> 수집 종료 (since={since})")
                    break
                # 🚀 [V10.0] 빈 응답 시 시간을 건너뛰어 재시도 (Upbit 과거 데이터 공백 대응)
                since += tf_ms * limit
                time.sleep(1)
                continue
            
            consecutive_empty = 0  # 정상 응답 시 리셋
            
            # 🚀 [V10.0] Upbit 등 일부 거래소는 역순 반환 → 정렬 보장
            ohlcv.sort(key=lambda x: x[0])
            
            all_ohlcv.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]
            if last_timestamp >= end_timestamp: break
            if last_timestamp <= since: since += tf_ms  # 🚀 [V10.0] 1ms 대신 1캔들만큼 이동
            else: since = last_timestamp + 1
            
            # 🚀 [V10.0] Upbit은 더 긴 대기 필요
            wait_time = max(exchange.rateLimit / 1000, 0.1) if hasattr(exchange, 'rateLimit') else 0.5
            if ex_lower == 'upbit':
                wait_time = max(wait_time, 0.2)
            time.sleep(wait_time)
            
            if progress_bar:
                # 🚀 [V19] 예상 다운로드 개수 대비 실제 다운로드 개수로 % 동적 계산
                pct = min(int(len(all_ohlcv) / total_expected * 100), 99)
                progress_bar.progress(pct, text=f"{len(all_ohlcv):,}/{int(total_expected):,} 캔들 수집 중...")

        if not all_ohlcv: return None
            
        df = pd.DataFrame(all_ohlcv, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms')
        df.set_index('Datetime', inplace=True)
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        # 최종 필터링: 종료일까지만
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df.index <= end_dt]
        
        if len(df) == 0:
            print(f"[Warning] 필터링 후 데이터가 0건입니다. (기간: {start_date} ~ {end_date})")
            return None
        
        if use_cache: df.to_parquet(cache_path)
        if progress_bar: progress_bar.progress(100, text=f"데이터 수집 완료: {len(df):,}개 캔들 ({timeframe})")
            
        return df
    except Exception as e:
        print(f"데이터 수집 에러 발생 [{exchange_id}/{symbol}/{timeframe}]: {e}")
        if progress_bar:
            progress_bar.progress(0, text=f"❌ 에러: {str(e)[:100]}")
        return None
