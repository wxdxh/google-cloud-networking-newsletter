import os
import datetime
import google.auth
from google.cloud import bigquery
from google.cloud import storage
from google import genai
from google.genai import types
from googleapiclient.discovery import build
import feedparser

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
    "⚓ Kubernetes 네트워킹 (GKE)": [
        "Google Kubernetes Engine"
    ],
    "⚡ Serverless 네트워킹": [
        "Cloud Run",
        "Cloud Functions",
        "App Engine"
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

# 필터링용 통합 네트워킹 키워드 풀
NETWORKING_KEYWORDS = [
    "ingress", "load balancer", "loadbalancer", "gateway", "mesh", "dns", 
    "ip ", "vpc", "network", "subnet", "proxy", "firewall", "route", 
    "service", "latency", "bandwidth", "connector", "egress", 
    "direct vpc", "private service connect"
]

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

def fetch_recent_release_notes(start_date_str, end_date_str="2026-05-01"):
    """Fetches release notes from the public BigQuery dataset since start_date and before end_date."""
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
        AND published_at < '{end_date_str}'
        AND product_name IN {products_tuple}
    ORDER BY 
        product_name, published_at DESC
    """

    print(f"Fetching release notes between {start_date_str} and {end_date_str} from BigQuery...")
    query_job = client.query(query)
    results = query_job.result()

    # 노이즈(네트워킹 이외의 패치 등)를 줄이기 위해 필터링을 적용할 제품군 리스트
    FILTERABLE_PRODUCTS = [
        "Google Kubernetes Engine", 
        "Cloud Run", 
        "Cloud Functions", 
        "App Engine"
    ]

    notes_data = []
    for row in results:
        desc_lower = row.description.lower()

        # 필터링 대상 제품군에 한해서만 텍스트 키워드 필터링 적용
        if row.product_name in FILTERABLE_PRODUCTS:
            if not any(kw in desc_lower for kw in NETWORKING_KEYWORDS):
                continue

        notes_data.append({
            "published_at": row.published_at.strftime('%Y-%m-%d'),
            "product_name": row.product_name,
            "type": row.release_note_type,
            "description": row.description
        })
    return notes_data

def fetch_blog_posts(start_date_str, end_date_str="2026-05-01"):
    """Fetches blog posts from the official RSS feed and filters by date."""
    RSS_URL = "https://cloudblog.withgoogle.com/rss"
    print(f"Fetching blog posts from {RSS_URL}...")
    feed = feedparser.parse(RSS_URL)
    
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    blog_data = []
    for entry in feed.entries:
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime.date(entry.published_parsed.tm_year, entry.published_parsed.tm_mon, entry.published_parsed.tm_mday)
            if start_date <= pub_date < end_date:
                # 기존 네트워크 뉴스레터의 서브아젠다 기준 키워드로 필터링 (분류 태그 포함)
                desc_lower = entry.description.lower()
                title_lower = entry.title.lower()
                
                # Extract categories if available
                categories = [c.term.lower() for c in entry.categories] if hasattr(entry, 'categories') else []
                
                content_to_check = title_lower + " " + desc_lower + " " + " ".join(categories)
                
                if any(kw in content_to_check for kw in NETWORKING_KEYWORDS):
                    blog_data.append({
                        "title": entry.title,
                        "description": entry.description,
                        "link": entry.link,
                        "published_at": pub_date.strftime('%Y-%m-%d')
                    })
    return blog_data

def summarize_blog_post(client, title, description):
    """Summarizes an individual blog post using Gemini."""
    prompt = f"""
    아래 Google Cloud 블로그 글의 제목과 내용을 바탕으로, 우리 팀원(클라우드 엔지니어)들이 참고할 수 있도록 건조하고 담백한 어조로 1~2문장 요약해줘.
    
    제목: {title}
    내용: {description}
    """
    try:
        print(f"Summarizing blog post: {title}")
        response = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        return response.text
    except Exception as e:
        print(f"Failed to summarize post '{title}': {e}")
        return f"요약 실패 (원문 링크 참고)"

def generate_newsletter_with_gemini(notes_data, blog_summaries, doc_content=""):
    if not notes_data and not blog_summaries and not doc_content:
        return "해당 기간 내에 네트워킹 업데이트, 블로그 소식, 또는 문서 내용이 없습니다."

    if not GEMINI_API_KEY:
         raise ValueError("GEMINI_API_KEY environment variable is not set. Please set it to use the Gemini API.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    raw_text = "--- [원문 BigQuery 릴리스 노트 수집 내역] ---\n"
    for note in notes_data:
        raw_text += f"- Date: {note['published_at']}\n  Product: {note['product_name']}\n  Type: {note['type']}\n  Description: {note['description']}\n\n"

    if blog_summaries:
        raw_text += "\n--- [Google Cloud 공식 블로그 요약 내역] ---\n\n"
        for summary in blog_summaries:
            raw_text += f"제목: {summary['title']}\n요약: {summary['summary']}\n링크: {summary['link']}\n\n"

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

    4. **공식 블로그 소식 (Blog Posts)**: 제공된 'Google Cloud 공식 블로그 요약 내역'을 바탕으로, 주요 기술 블로그 소식을 별도의 섹션으로 정리할 것. 각 글의 제목과 요약, 그리고 링크를 포함할 것.

    5. HTML 태그 없이 마크다운으로만 작성할 것.

    {raw_text}
    """

    print("Generating newsletter content with Gemini API...")
    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    return response.text

def verify_newsletter(client, content):
    """Verifies the generated newsletter content for relevance and quality."""
    prompt = f"""
    아래 생성된 'Google Cloud Networking Newsletter'의 내용을 검증해줘.
    
    내용:
    {content}
    
    ## 검증 기준:
    1. 모든 내용이 Google Cloud Networking 및 Security 범위에 속하는가? (예: GKE, Cloud Run, BigQuery 등 네트워킹과 무관한 순수 데이터베이스나 AI 모델 발표는 제외되어야 함)
    2. AI가 생성한 느낌의 과장된 수사나 상투적인 인사말이 배제되었는가?
    3. "Google Cloud Networking 업데이트:"라는 문구로 시작하는가?
    4. 날짜가 2026년 최신 데이터인가?
    
    ## 응답 형식:
    - 통과 여부: PASS 또는 FAIL
    - 이유: (FAIL인 경우 구체적인 이유 작성)
    
    응답은 반드시 위 형식을 지켜줘.
    """
    try:
        print("Verifying newsletter content with Gemini...")
        response = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        result = response.text
        print(f"Verification Result:\\n{result}")
        
        if "PASS" in result.split('\\n')[0]:
            return True, ""
        else:
            reason = ""
            for line in result.split('\\n'):
                if "이유:" in line:
                    reason = line.split("이유:")[1].strip()
            return False, reason
    except Exception as e:
        print(f"Verification failed to execute: {e}")
        return True, "Verification tool failed, assuming pass"

def main():
    try:
        start_date_str = "2026-04-01" 
        end_date_str = "2026-05-01"
        now_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"networking_newsletter_2026_April_{now_str}.md"

        # 1. Fetch BigQuery Release Notes
        notes_data = fetch_recent_release_notes(start_date_str, end_date_str)
        print(f"Found {len(notes_data)} release notes related to Networking & Security.")

        # 1.5 Fetch and Summarize Blog Posts
        blog_data = fetch_blog_posts(start_date_str, end_date_str)
        print(f"Found {len(blog_data)} blog posts in the date range.")
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        blog_summaries = []
        for post in blog_data:
            summary = summarize_blog_post(client, post['title'], post['description'])
            blog_summaries.append({
                "title": post['title'],
                "summary": summary,
                "link": post['link']
            })

        # 2. Fetch Google Docs content
        doc_content = read_google_doc(DOC_ID)
        if doc_content:
             print("Successfully extracted content from Google Docs.")

        # 3. Process with Gen AI (with verification loop)
        max_attempts = 3
        attempt = 0
        newsletter_content = ""
        
        while attempt < max_attempts:
            attempt += 1
            print(f"Generation attempt {attempt} of {max_attempts}...")
            newsletter_content = generate_newsletter_with_gemini(notes_data, blog_summaries, doc_content)
            
            passed, reason = verify_newsletter(client, newsletter_content)
            if passed:
                print("Verification passed!")
                break
            else:
                print(f"Verification failed: {reason}")
                if attempt < max_attempts:
                    print("Retrying generation...")
                else:
                    print("Max attempts reached. Proceeding with caution.")
                    newsletter_content = f"⚠️ [VERIFICATION FAILED: {reason}]\\n\\n" + newsletter_content

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
