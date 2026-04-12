import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_discord_alert(study_name: str, best_value: float, engine: str, pair: str):
    """최적화 완료 알림 전송 (타임아웃 강화)"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url or "YOUR_ID" in webhook_url:
        return False, "URL 미설정"
        
    try:
        content = (
            "✅ **[최적화 완료]**\n"
            f"> 엔진: `{engine}` | 대상: `{pair}`\n"
            f"> **최고 수익률: {best_value:.2f}%**"
        )
        # 타임아웃을 10초로 늘리고 재시도 로직은 호출부에서 관리
        res = requests.post(webhook_url, json={"content": content}, timeout=10)
        res.raise_for_status()
        return True, "성공"
    except Exception as e:
        print(f"[Discord Error] {str(e)}")
        return False, str(e)

def send_discord_error(error_msg: str, pair: str = "Unknown", engine: str = "Unknown"):
    """긴급 에러 알림 전송 (강력한 예외 처리)"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url or "YOUR_ID" in webhook_url:
        return False, "URL 미설정"
        
    try:
        content = (
            "🚨 **[긴급 시스템 오류]**\n"
            f"> 대상: `{pair}` ({engine})\n"
            f"> **메시지: `{error_msg}`**"
        )
        res = requests.post(webhook_url, json={"content": content}, timeout=10)
        res.raise_for_status()
        return True, "성공"
    except Exception as e:
        # 알림 전송 자체가 실패할 경우 표준 출력에 남겨 서버 로그에서 확인 가능하게 함
        print(f"[CRITICAL ERR] Discord Notify Failed: {str(e)}")
        return False, str(e)

def send_discord_progress(study_name: str, pair: str, progress_pct: int, best_val: float):
    """최적화 진행 상황(25/50/75%) 알림 전송"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url or "YOUR_ID" in webhook_url:
        return False
        
    try:
        content = (
            f"📊 **[백테스트 진행 현황 - {progress_pct}%]**\n"
            f"> 대상: `{pair}` | 세션명: `{study_name}`\n"
            f"> 현재 최고 수익률: **{best_val:.2f}%**"
        )
        requests.post(webhook_url, json={"content": content}, timeout=5)
        return True
    except:
        return False
