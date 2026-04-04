#!/bin/bash
echo "🚀 Vultr 서버 백테스트 환경 자동 설정 스크립트 시작..."

# 시스템 패키지 업데이트 및 Redis 설치
sudo apt-get update
sudo apt-get install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# 파이썬 패키지 설치
pip install -r requirements.txt

echo "✅ 환경 설정이 완료되었습니다."
echo "▶️ 워커 실행: celery -A core.tasks worker --loglevel=info &"
echo "▶️ 웹 실행: streamlit run app.py &"
