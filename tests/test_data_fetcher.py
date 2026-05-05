import sys
import os
from unittest.mock import MagicMock, patch

# Mock dependencies before importing the module under test
mock_modules = ['ccxt', 'streamlit', 'redis', 'pandas']
for module in mock_modules:
    if module not in sys.modules:
        sys.modules[module] = MagicMock()

from core.data_fetcher import get_cache_path, CACHE_DIR

def test_get_cache_path_deterministic():
    """Verify that get_cache_path returns the same path for the same inputs."""
    params = {
        'exchange_id': 'binance',
        'symbol': 'BTC/USDT',
        'timeframe': '1h',
        'start_date': '2023-01-01',
        'end_date': '2023-01-02',
        'padding_candles': 250
    }

    with patch('os.makedirs'), patch('os.path.exists', return_value=True):
        path1 = get_cache_path(**params)
        path2 = get_cache_path(**params)

    assert path1 == path2
    # Pre-calculated MD5 for 'binance_BTC/USDT_1h_2023-01-01_2023-01-02_p250_v43'
    # is '7ee6e05163fd6d001a6fab9e1f202067'
    assert '7ee6e05163fd6d001a6fab9e1f202067' in path1
    assert path1.endswith('.pkl')
    assert path1.startswith(CACHE_DIR)

def test_get_cache_path_uniqueness():
    """Verify that different inputs result in different cache paths."""
    base_params = {
        'exchange_id': 'binance',
        'symbol': 'BTC/USDT',
        'timeframe': '1h',
        'start_date': '2023-01-01',
        'end_date': '2023-01-02',
        'padding_candles': 250
    }

    with patch('os.makedirs'), patch('os.path.exists', return_value=True):
        path_base = get_cache_path(**base_params)

        # Change exchange
        params_diff_exchange = base_params.copy()
        params_diff_exchange['exchange_id'] = 'upbit'
        assert get_cache_path(**params_diff_exchange) != path_base

        # Change symbol
        params_diff_symbol = base_params.copy()
        params_diff_symbol['symbol'] = 'ETH/USDT'
        assert get_cache_path(**params_diff_symbol) != path_base

        # Change timeframe
        params_diff_tf = base_params.copy()
        params_diff_tf['timeframe'] = '15m'
        assert get_cache_path(**params_diff_tf) != path_base

        # Change padding
        params_diff_padding = base_params.copy()
        params_diff_padding['padding_candles'] = 100
        assert get_cache_path(**params_diff_padding) != path_base

def test_get_cache_path_creates_directory():
    """Verify that get_cache_path creates the cache directory if it doesn't exist."""
    params = {
        'exchange_id': 'binance',
        'symbol': 'BTC/USDT',
        'timeframe': '1h',
        'start_date': '2023-01-01',
        'end_date': '2023-01-02',
        'padding_candles': 250
    }

    with patch('os.path.exists') as mock_exists, patch('os.makedirs') as mock_makedirs:
        # Simulate directory missing
        mock_exists.return_value = False

        get_cache_path(**params)

        # Check if os.makedirs was called with CACHE_DIR
        mock_makedirs.assert_called_once_with(CACHE_DIR)
