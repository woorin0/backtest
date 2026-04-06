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
# 이전 프로세스 종료 (재실행 시 꼬임 방지)
pkill -f celery
pkill -f streamlit

# 무중단 백그라운드 실행 (로그는 각각의 log 파일에 저장됨)
nohup celery -A core.tasks:celery_app worker --loglevel=info > celery_worker.log 2>&1 &
nohup streamlit run app.py > streamlit_app.log 2>&1 &

echo "▶️ 워커와 웹서버가 무중단 모드(nohup)로 실행되었습니다."
