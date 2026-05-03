import sys
from unittest.mock import MagicMock
import pytest

# Mock missing dependencies before importing the module under test
sys.modules['ccxt'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['streamlit'] = MagicMock()
sys.modules['pandas'] = MagicMock()

from core.data_fetcher import get_timeframe_ms

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

def test_get_timeframe_ms_empty_string():
    with pytest.raises(IndexError):
        get_timeframe_ms("")

def test_get_timeframe_ms_missing_number():
    with pytest.raises(ValueError):
        get_timeframe_ms("m")

def test_get_timeframe_ms_invalid_number():
    with pytest.raises(ValueError):
        get_timeframe_ms("abcm")

def test_get_timeframe_ms_none_input():
    with pytest.raises(TypeError):
        get_timeframe_ms(None)
