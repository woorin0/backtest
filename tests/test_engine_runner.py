import sys
from unittest.mock import MagicMock

# Mock dependencies that might be missing in the environment
mock_modules = ['pandas', 'numpy', 'backtrader', 'vectorbt']
for module in mock_modules:
    if module not in sys.modules:
        sys.modules[module] = MagicMock()

from core.engine_runner import run_backtest

def test_run_backtest_invalid_engine():
    """
    Verify that run_backtest returns False and an appropriate error message
    when an unsupported engine is requested.
    """
    # Arrange
    engine = "unsupported_engine"
    code_str = "print('hello')"
    data = MagicMock()

    # Act
    success, message = run_backtest(engine, code_str, data)

    # Assert
    assert success is False
    assert message == "미지원 엔진"
