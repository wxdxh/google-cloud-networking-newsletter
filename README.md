# 🌐 Google Cloud Networking Newsletter Automation

이 프로젝트는 **Google Cloud Networking 및 Security** 제품군의 최신 업데이트 뉴스를 자동으로 수집하고, AI(Gemini)를 활용하여 사내/팀 내부 공유용 **마크다운(.md) 뉴스레터**를 생성하는 자동화 도구입니다.

---

## 🚀 주요 기능
1. **최신 릴리스 노트 수집**: Google Cloud의 공용 BigQuery 데이터셋에서 Networking 및 Security 관련 업데이트 내역을 자동 조회합니다.
2. **내부 가이드 연동 (선택)**: 정해진 Google Doc에서 팀 내 추가 기사나 메모를 읽어와 뉴스레터에 함께 녹여냅니다.
3. **공식 블로그 RSS 연동**: Google Cloud 공식 블로그 피드를 읽어와 최신 소식을 추가합니다.
4. **개별 요약 및 키워드 필터링**: 블로그 글을 개별적으로 요약하여 품질을 높이고, 네트워킹 관련 키워드로 필터링하여 요약 대상을 최적화합니다.
5. **자동 검증 및 재시도**: 생성된 뉴스레터가 네트워킹/보안 범위에 맞는지 AI가 스스로 검증하고, 이상이 있을 경우 자동으로 재생성을 시도합니다.
6. **AI 기반 요약 생성**: 최신 Gemini 모델을 활용하여 담백하고 엔지니어링 중심의 테크니컬 리뷰 톤으로 최종 뉴스레터를 작성합니다.
7. **다양한 출력 모드**: 생성된 뉴스레터를 로컬 환경에 파일(.md)로 저장하거나, Google Cloud Storage(GCS) 버킷에 고유한 파일명(타임스탬프 포함)으로 자동 업로드할 수 있습니다.

---

## 📂 파일 구조
* `generate_newsletter.py`: 뉴스레터 생성 메인 파이썬 스크립트
* `requirements.txt`: 파이썬 패키지 의존성 목록
* `Dockerfile`: 컨테이너 이미지 빌드 설정 (Cloud Run Job 대응)
* `deploy.sh`: GCP(Cloud Run Job) 배포를 위한 쉘 스크립트

---

## 🛠️ 로컬 실행 방법

### 1. 사전 준비
* **Python 3.9** 이상
* **Gemini API Key** 발급
* **GCP 인증**: 로컬 터미널에서 `gcloud auth application-default login`을 실행해 인증 환경이 갖춰져 있어야 합니다.

### 2. 설치 및 실행
```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate

# 의존성 팩키지 설치
pip install -r requirements.txt

# 필수 환경 변수 설정
export GEMINI_API_KEY="본인의_Gemini_API_키"
export GOOGLE_CLOUD_PROJECT="본인의_GCP_프로젝트_ID"

# (선택사항)
# export GOOGLE_DOC_ID="참조할_Google_Docs_인증ID"
# export GCS_BUCKET_NAME="출력물을_저장할_GCS_버킷명"

# 스크립트 가동
python generate_newsletter.py
```

---

## ☁️ Google Cloud (Cloud Run Job) 배포 방법

서버리스 환경에서 매월/매주 자동 가동(Cloud Scheduler 연결 등)을 원할 경우 컨테이너 배포를 진행합니다.

1. **`deploy.sh` 열기** 및 상위 환경 변수 커스텀:
   ```bash
   export PROJECT_ID="본인의_프로젝트_ID"
   export SERVICE_ACCOUNT="사용할_서비스_계정_이메일"
   export GCS_BUCKET_NAME="결과물이_올라갈_버킷명"
   ```
2. **스크립트 실행**:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```
   * 스크립트를 실행하면 **Artifact Registry 생성 ➡️ Cloud Build 활용 빌드 ➡️ Cloud Run Job 배포** 순서가 한 번에 이루어집니다.
   * API 키와 같은 민감 개인 정보는 **Secret Manager**를 생성하여 `gemini-api-key`라는 이름으로 주입하는 것을 권장합니다.

---

## 🤝 기여 및 문의
코드 수정이나 개선 사항이 있다면 Pull Request를 보내주세요!
