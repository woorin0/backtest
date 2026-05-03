import sys
from unittest.mock import MagicMock

# Mock missing dependencies before importing the module under test
sys.modules['ccxt'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['streamlit'] = MagicMock()
sys.modules['pandas'] = MagicMock()

import os
import hashlib
from unittest.mock import patch

from core.data_fetcher import get_timeframe_ms, get_cache_path, CACHE_DIR

def test_get_timeframe_ms_minutes():
    assert get_timeframe_ms('1m') == 60000
    assert get_timeframe_ms('5m') == 300000
    assert get_timeframe_ms('15m') == 900000

def test_get_timeframe_ms_hours():
    assert get_timeframe_ms('1h') == 3600000
    assert get_timeframe_ms('4h') == 14400000

def test_get_timeframe_ms_days():
    assert get_timeframe_ms('1d') == 86400000
    assert get_timeframe_ms('3d') == 259200000

def test_get_timeframe_ms_weeks():
    assert get_timeframe_ms('1w') == 604800000
    assert get_timeframe_ms('2w') == 1209600000

def test_get_timeframe_ms_default():
    # Default is 1 hour (3600000 ms) for unknown units
    assert get_timeframe_ms('1x') == 3600000
    assert get_timeframe_ms('10z') == 3600000

def test_get_cache_path_deterministic():
    args = ("binance", "BTC/USDT", "1h", "2023-01-01", "2023-01-31")
    path1 = get_cache_path(*args)
    path2 = get_cache_path(*args)
    assert path1 == path2

@patch('os.path.exists')
@patch('os.makedirs')
def test_get_cache_path_creates_dir_if_not_exists(mock_makedirs, mock_exists):
    mock_exists.return_value = False

    exchange_id = "binance"
    symbol = "BTC/USDT"
    timeframe = "1h"
    start_date = "2023-01-01"
    end_date = "2023-01-31"
    padding_candles = 250

    path = get_cache_path(exchange_id, symbol, timeframe, start_date, end_date, padding_candles)

    mock_makedirs.assert_called_once_with(CACHE_DIR)

    key = f"{exchange_id}_{symbol}_{timeframe}_{start_date}_{end_date}_p{padding_candles}_v43"
    expected_hash = hashlib.md5(key.encode()).hexdigest()
    expected_path = os.path.join(CACHE_DIR, f"ohlcv_{expected_hash}.pkl")

    assert path == expected_path

@patch('os.path.exists')
@patch('os.makedirs')
def test_get_cache_path_does_not_create_dir_if_exists(mock_makedirs, mock_exists):
    mock_exists.return_value = True

    exchange_id = "upbit"
    symbol = "KRW-BTC"
    timeframe = "1d"
    start_date = "2023-02-01"
    end_date = "2023-02-28"
    padding_candles = 100

    path = get_cache_path(exchange_id, symbol, timeframe, start_date, end_date, padding_candles)

    mock_makedirs.assert_not_called()

    key = f"{exchange_id}_{symbol}_{timeframe}_{start_date}_{end_date}_p{padding_candles}_v43"
    expected_hash = hashlib.md5(key.encode()).hexdigest()
    expected_path = os.path.join(CACHE_DIR, f"ohlcv_{expected_hash}.pkl")

    assert path == expected_path
