import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_discord_alert(metrics, engine: str, pair: str):
    """웹훅 URL로 결과 딕셔너리를 전송하는 알림 모듈"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    # 기본 플레이스홀더 템플릿일때의 스킵 로직
    if "YOUR_ID" in webhook_url or not webhook_url.startswith("http"):
        return False, "유효한 웹훅 URL이 설정되지 않았습니다. (.env 수정 필요)"
        
    try:
        content_lines = [
            "✅ **[백테스트 완료 알림]**",
            f"**사용 엔진**: `{engine}` | **대상 거래쌍**: `{pair}`",
            "```yaml",
        ]
        
        for k, v in metrics.items():
            content_lines.append(f"{k}: {v}")
            
        content_lines.append("```")
        
        payload = {"content": "\n".join(content_lines)}
        
        # 3초 타임아웃
        response = requests.post(webhook_url, json=payload, timeout=3)
        response.raise_for_status()
        
        return True, "전송 완료"
    except Exception as e:
        return False, f"Network/HTTP Exception: {str(e)}"
