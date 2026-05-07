import sys
import os
from unittest.mock import MagicMock, patch

# Mock dependencies that are missing in the environment
mock_modules = ['requests', 'dotenv']
for module in mock_modules:
    if module not in sys.modules:
        sys.modules[module] = MagicMock()

from core.notifier import send_discord_error, send_discord_alert, send_discord_progress

# Tests for send_discord_error
def test_send_discord_error_no_url():
    """Verify send_discord_error returns False when webhook URL is missing."""
    with patch('os.getenv', return_value=""):
        success, msg = send_discord_error("Test error")
        assert success is False
        assert msg == "URL 미설정"

def test_send_discord_error_placeholder_url():
    """Verify send_discord_error returns False when webhook URL is placeholder."""
    with patch('os.getenv', return_value="https://discord.com/api/webhooks/YOUR_ID"):
        success, msg = send_discord_error("Test error")
        assert success is False
        assert msg == "URL 미설정"

def test_send_discord_error_success():
    """Verify send_discord_error returns True on successful request."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post', return_value=mock_response) as mock_post:
            success, msg = send_discord_error("Test error", "BTC/USDT", "vectorbt")
            assert success is True
            assert msg == "성공"
            mock_post.assert_called_once()
            # Verify content structure
            _, kwargs = mock_post.call_args
            assert "🚨 **[긴급 시스템 오류]**" in kwargs['json']['content']
            assert "BTC/USDT" in kwargs['json']['content']
            assert "vectorbt" in kwargs['json']['content']
            assert "Test error" in kwargs['json']['content']

def test_send_discord_error_http_error():
    """Verify send_discord_error returns False on HTTP error."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("HTTP Error")

    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post', return_value=mock_response):
            success, msg = send_discord_error("Test error")
            assert success is False
            assert "HTTP Error" in msg

def test_send_discord_error_exception():
    """Verify send_discord_error returns False on connection error or other exceptions."""
    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post', side_effect=Exception("Connection Timeout")):
            success, msg = send_discord_error("Test error")
            assert success is False
            assert "Connection Timeout" in msg

# Tests for send_discord_alert
def test_send_discord_alert_success():
    """Verify send_discord_alert returns True on successful request."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post', return_value=mock_response) as mock_post:
            success, msg = send_discord_alert("StudyA", 15.5, "vectorbt", "BTC/USDT")
            assert success is True
            assert msg == "성공"
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert "✅ **[최적화 완료]**" in kwargs['json']['content']
            assert "15.50%" in kwargs['json']['content']

def test_send_discord_alert_no_url():
    """Verify send_discord_alert returns False when URL is missing."""
    with patch('os.getenv', return_value=""):
        success, msg = send_discord_alert("StudyA", 15.5, "vectorbt", "BTC/USDT")
        assert success is False
        assert msg == "URL 미설정"

# Tests for send_discord_progress
def test_send_discord_progress_success():
    """Verify send_discord_progress returns True on successful request."""
    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post') as mock_post:
            result = send_discord_progress("StudyA", "BTC/USDT", 25, 10.5)
            assert result is True
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert "📊 **[백테스트 진행 현황 - 25%]**" in kwargs['json']['content']

def test_send_discord_progress_no_url():
    """Verify send_discord_progress returns False when URL is missing."""
    with patch('os.getenv', return_value=""):
        result = send_discord_progress("StudyA", "BTC/USDT", 25, 10.5)
        assert result is False

def test_send_discord_progress_exception():
    """Verify send_discord_progress returns False on exception."""
    with patch('os.getenv', return_value="https://discord.com/api/webhooks/valid_url"):
        with patch('requests.post', side_effect=Exception("Error")):
            result = send_discord_progress("StudyA", "BTC/USDT", 25, 10.5)
            assert result is False
