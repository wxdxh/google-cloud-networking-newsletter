import os
import datetime
import google.auth
from google.cloud import bigquery
from google.cloud import storage
from google import genai
from google.genai import types
from googleapiclient.discovery import build

# Configuration
# ==========================================
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "YOUR_GCP_PROJECT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

DATASET = "bigquery-public-data.google_cloud_release_notes.release_notes"

# Google Doc ID (URL에서 https://docs.google.com/document/d/<DOC_ID>/edit 부분 추출)
DOC_ID = os.environ.get("GOOGLE_DOC_ID", "YOUR_GOOGLE_DOC_ID")

# Expanded Networking & Security Products Category Mapping
PRODUCT_CATEGORIES = {
    "🌐 네트워크 인프라 및 연결 (Connectivity)": [
        "Virtual Private Cloud",
        "Cloud Interconnect",
        "Cloud VPN",
        "Cloud Router",
        "Cloud NAT",
        "Network Connectivity Center"
    ],
    "🚀 트래픽 라우팅 및 엣지 전송 (Delivery & Edge)": [
        "Cloud Load Balancing",
        "Cloud CDN",
        "Cloud DNS"
    ],
    "🛡️ 네트워크 보안 (Security)": [
        "Google Cloud Armor",
        "Cloud NGFW", 
        "Cloud IDS",
        "Identity-Aware Proxy"
    ],
    "📊 네트워크 운영 및 가시성 (Observability)": [
        "Network Intelligence Center",
        "Service Directory"
    ]
}

NETWORKING_PRODUCTS = [
    product for category_list in PRODUCT_CATEGORIES.values() for product in category_list
]
# ==========================================

def read_google_doc(doc_id):
    """Fetches text content from the specified Google Doc using Application Default Credentials."""
    if doc_id == "YOUR_GOOGLE_DOC_ID" or not doc_id:
        return ""
        
    try:
        # GCP 환경의 기본 인증정보(Service Account 또는 gcloud auth)를 사용합니다.
        # 이 서비스 계정 이메일에 해당 Google Doc에 대한 "읽기 권한"을 부여해야 합니다.
        credentials, project = google.auth.default(scopes=['https://www.googleapis.com/auth/documents.readonly'])
        service = build('docs', 'v1', credentials=credentials)
        
        print(f"Fetching content from Google Doc (ID: {doc_id})...")
        document = service.documents().get(documentId=doc_id).execute()
        
        doc_content = ""
        for element in document.get('body').get('content'):
            if 'paragraph' in element:
                elements = element.get('paragraph').get('elements')
                for elem in elements:
                    if 'textRun' in elem:
                        doc_content += elem.get('textRun').get('content')
                        
        # 문서 내용이 너무 길어지지 않게 3000자 이내로 자름 (안전장치)
        return doc_content[:3000]
    except Exception as e:
        print(f"An error occurred while reading Google Doc {doc_id}: {e}")
        return ""

def fetch_recent_release_notes(start_date_str):
    """Fetches release notes from the public BigQuery dataset since start_date."""
    client = bigquery.Client(project=PROJECT_ID)
    
    products_tuple = tuple(NETWORKING_PRODUCTS)
    
    query = f"""
    SELECT 
        published_at,
        product_name,
        release_note_type,
        description
    FROM 
        `{DATASET}`
    WHERE 
        published_at >= '{start_date_str}'
        AND product_name IN {products_tuple}
    ORDER BY 
        product_name, published_at DESC
    """
    
    print(f"Fetching release notes since {start_date_str} from BigQuery...")
    query_job = client.query(query)
    results = query_job.result()
    
    notes_data = []
    for row in results:
        notes_data.append({
            "published_at": row.published_at.strftime('%Y-%m-%d'),
            "product_name": row.product_name,
            "type": row.release_note_type,
            "description": row.description
        })
    return notes_data

def generate_newsletter_with_gemini(notes_data, doc_content=""):
    if not notes_data and not doc_content:
        return "해당 기간 내에 네트워킹 업데이트나 문서 내용이 없습니다."
        
    if not GEMINI_API_KEY:
         raise ValueError("GEMINI_API_KEY environment variable is not set. Please set it to use the Gemini API.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    raw_text = "--- [원문 BigQuery 릴리스 노트 수집 내역] ---\n"
    for note in notes_data:
        raw_text += f"- Date: {note['published_at']}\n  Product: {note['product_name']}\n  Type: {note['type']}\n  Description: {note['description']}\n\n"

    if doc_content:
        raw_text += "\n--- [구글 문서(Google Docs) 추가 정리 내역 요약] ---\n\n"
        raw_text += doc_content + "\n\n"

    category_context = "    [필수 대분류 그룹 규칙]\n"
    for cat, prods in PRODUCT_CATEGORIES.items():
        category_context += f"    - {cat}: {', '.join(prods)}\n"

    prompt = f"""
    아래 제공된 Google Cloud 제품군 릴리스 노트(영문) 및 '구글 문서(Google Docs)' 추가 참고 내용을 바탕으로, 조직 내부 공유용 'Google Cloud Networking Newsletter'를 마크다운 형식으로 작성해.

    ## 절대 준수 사항 (톤앤매너 및 데이터 검증):
    - AI가 자동으로 생성한 느낌을 주는 과장된 수사, 상투적인 인사말은 전부 배제할 것.
    - 실제 클라우드 엔지니어가 팀원들에게 공유하는 건조하고 담백한 '테크니컬 리뷰' 스타일로 작성할 것.
    - [중요] 문서의 시작은 반드시 **"Google Cloud Networking 업데이트:"**라는 문구로 시작할 것.
    - [중요] '엔지니어 코멘트'나 주관적인 분석 섹션은 절대 포함하지 말 것.
    - [중요] 제공된 원문 데이터의 'Date'(연도)를 반드시 더블체크하여 2026년 최신 데이터만 포함할 것.

    ## 정보 구성 요구사항:
    1. **서두 요약 (Summary)**: 
       - "Google Cloud Networking 업데이트:"로 시작하여 이번 분기의 핵심 업데이트(Connectivity, Delivery, Security, Observability 전 분야)를 3~4문장으로 건조하게 요약할 것.
    2. 아래 제공된 [필수 대분류 그룹 규칙]을 완전히 준수하여 본문을 구성할 것.
{category_context}
    3. **각 세부 업데이트 항목(단일 기능 릴리스) 구성**:
       반드시 아래의 형식을 엄격히 준수하여 작성할 것 (각 항목마다 이 구조를 반복):
       
       **[핵심 요약 제목]**
       - **적용 서비스**: {{특정 서비스 명칭}}
       - **업데이트 상세**: {{핵심 업데이트 또는 변경 사항을 날짜를 포함하여 1~2문장으로 요약}}
       - **실무 활용**: {{팀을 위한 실무적 시사점 또는 필요한 조치 사항}}
       - **관련정보**: {{해당 업데이트 정보를 확인할 수 있는 URL 링크}}

    4. HTML 태그 없이 마크다운으로만 작성할 것.

    {raw_text}
    """

    print("Generating newsletter content with Gemini API...")
    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    return response.text

def main():
    try:
        start_date_str = "2026-01-01" 
        output_filename = "networking_newsletter_2026_Q1.md"
        
        # 1. Fetch BigQuery Release Notes
        notes_data = fetch_recent_release_notes(start_date_str)
        print(f"Found {len(notes_data)} release notes related to Networking & Security.")
        
        # 2. Fetch Google Docs content
        doc_content = read_google_doc(DOC_ID)
        if doc_content:
             print("Successfully extracted content from Google Docs.")
        
        # 3. Process with Gen AI
        newsletter_content = generate_newsletter_with_gemini(notes_data, doc_content)
        
        # 4. Output processing
        if GCS_BUCKET_NAME:
            storage_client = storage.Client(project=PROJECT_ID)
            bucket = storage_client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(output_filename)
            blob.upload_from_string(newsletter_content, content_type='text/markdown; charset=utf-8')
            print(f"Newsletter successfully generated and uploaded to GCS bucket '{GCS_BUCKET_NAME}' as {output_filename}")
        else:
            # Cloud Run 등 ephemeral 환경을 고려해 /tmp 사용 혹은 로컬에 작성
            local_path = f"/tmp/{output_filename}"
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(newsletter_content)
            print(f"Newsletter generated and saved locally to {local_path} (Set GCS_BUCKET_NAME to upload to Cloud Storage)")
        
    except Exception as e:
         print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
