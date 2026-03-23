FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 업데이트 및 CA 인증서 설정
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 어플리케이션 소스 복사
COPY generate_newsletter.py .

# 컨테이너 실행 시 기본 엔트리포인트 지정
CMD ["python", "generate_newsletter.py"]
