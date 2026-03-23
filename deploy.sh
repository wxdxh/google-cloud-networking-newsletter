#!/bin/bash
# ==========================================
# Google Cloud Run Job 배포 스크립트
# ==========================================

# 1. 필수 환경 변수 설정 (사용자 환경에 맞게 수정 필요)
export PROJECT_ID="cdn-compliance"
export REGION="asia-northeast3" # 서울 리전
export REPO_NAME="newsletter-repo"
export IMAGE_NAME="newsletter-generator"
export JOB_NAME="newsletter-job"
export SERVICE_ACCOUNT="10257057738-compute@developer.gserviceaccount.com"

# API 키 및 GCS 버킷 (직접 입력 혹은 Secret Manager 사용 권장)
export GEMINI_API_KEY="" # Using Secret Manager instead
export GOOGLE_DOC_ID="" # Not provided
export GCS_BUCKET_NAME="newsletter-output-cdn-compliance"

echo "Deploying to Project: ${PROJECT_ID}"

# 2. Artifact Registry 리포지토리가 없으면 생성
gcloud artifacts repositories describe ${REPO_NAME} \
    --project=${PROJECT_ID} --location=${REGION} > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Creating Artifact Registry repository '${REPO_NAME}'..."
    gcloud artifacts repositories create ${REPO_NAME} \
        --repository-format=docker \
        --location=${REGION} \
        --project=${PROJECT_ID} \
        --description="Repository for newsletter generator"
fi

# 3. Cloud Build를 이용한 컨테이너 이미지 빌드 및 푸시
IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest"
echo "Building and pushing container image to ${IMAGE_URL}..."
gcloud builds submit --tag ${IMAGE_URL} . --project=${PROJECT_ID}

# 4. Cloud Run Job 생성 또는 업데이트
echo "Deploying Cloud Run Job '${JOB_NAME}'..."
gcloud run jobs deploy ${JOB_NAME} \
    --image ${IMAGE_URL} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --service-account ${SERVICE_ACCOUNT} \
    --set-env-vars GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_DOC_ID=${GOOGLE_DOC_ID},GCS_BUCKET_NAME=${GCS_BUCKET_NAME} \
    --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
    --max-retries 0 \
    --task-timeout 600s

# 참고: --set-secrets 를 통해 Secret Manager에서 키를 주입하는 방식을 사용했습니다.
# 만약 Secret Manager 설정을 하지 않으셨다면, 아래와 같이 환경변수로 직접 주입할 수도 있습니다 (보안상 권장하지 않음).
# --set-env-vars GEMINI_API_KEY=${GEMINI_API_KEY}

echo "=========================================="
echo "Deployment Complete!"
echo "To run the job manually, execute:"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT_ID}"
echo "=========================================="
