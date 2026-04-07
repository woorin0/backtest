import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_discord_alert(study_name: str, best_value: float, engine: str, pair: str):
    """웹훅 URL로 완료 알림만 전송하는 알림 모듈"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    if "YOUR_ID" in webhook_url or not webhook_url.startswith("http"):
        return False, "유효한 웹훅 URL이 설정되지 않았습니다. (.env 수정 필요)"
        
    try:
        content_lines = [
            "✅ **[Optuna 백테스트 최적화 완료 알림]**",
            f"**사용 엔진**: `{engine}` | **대상 거래쌍**: `{pair}`",
            f"**🏆 최고 수익률**: `{best_value:.2f}%`",
            "> 자세한 Top 30 조합 결과는 웹 대시보드에서 엑셀 파일로 다운로드해 주세요."
        ]
        
        payload = {"content": "\n".join(content_lines)}
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        
        return True, "전송 완료"
    except Exception as e:
        return False, f"Network/HTTP Exception: {str(e)}"

def send_discord_error(error_msg: str, pair: str = "Unknown", engine: str = "Unknown"):
    """웹훅 URL로 에러 알림을 전송하는 모듈"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    if "YOUR_ID" in webhook_url or not webhook_url.startswith("http"):
        return False, "유효한 웹훅 URL이 설정되지 않았습니다."
        
    try:
        content_lines = [
            "🚨 **[Optuna 백테스트 최적화 오류 발생]**",
            f"**대상**: `{pair}` ({engine})",
            f"**❌ 에러 메시지**: `{error_msg}`",
            "> 대시보드 로그를 확인하여 상세 원인을 파악해 주세요."
        ]
        
        payload = {"content": "\n".join(content_lines)}
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        
        return True, "전송 완료"
    except Exception as e:
        return False, f"Network/HTTP Exception: {str(e)}"
