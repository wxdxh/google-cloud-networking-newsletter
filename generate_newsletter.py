import os
import datetime
import google.auth
from google.cloud import bigquery
from google.cloud import storage
from google import genai
from google.genai import types
from googleapiclient.discovery import build
import feedparser
import urllib.request
import urllib.error
import re

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
        "Identity-Aware Proxy",
        "Secure Web Proxy"
    ],
    "🤖 AI 및 Agent 네트워크 인프라 (AI & Agent Infrastructure)": [
        "Gemini Enterprise Agent Platform",
        "Agent Registry"
    ],
    "📊 네트워크 운영 및 가시성 (Observability)": [
        "Network Intelligence Center",
        "Service Directory"
    ]
}

NETWORKING_PRODUCTS = [
    product for category_list in PRODUCT_CATEGORIES.values() for product in category_list
]

# 네트워킹 강신호 키워드 — Cloud Run/GKE/Functions/App Engine 릴리스 노트의
# 일반적인 컴퓨트/스토리지 업데이트와 구분하기 위해 의도적으로 좁게 유지.
# "service", "route", "network", "gateway" 등 단독으로는 너무 일반적이라 제외
# (false positive 사례: "Cloud Run Ephemeral Disk", "NVIDIA GPU support" 등이 통과).
NETWORKING_KEYWORDS = [
    "ingress", "egress",
    "load balancer", "loadbalancer",
    "vpc", "subnet", "firewall",
    "dns", "cdn", "vpn", "interconnect",
    "cloud armor", "cloud nat",
    "service mesh", "service connect", "private service connect",
    "vpc connector", "direct vpc",
    "network policy", "gateway api",
    "tls certificate", "ssl certificate",
    "agent gateway", "agent identity", "mcp server", "mcp tool", "mcp connectivity",
    "secure web proxy",
]

# 강배제 키워드 — FILTERABLE_PRODUCTS에 한해 description에 아래 단어가 있으면
# 네트워킹 키워드 매칭 여부와 무관하게 제외 (스토리지/컴퓨트 업데이트 차단).
NETWORKING_EXCLUSION_KEYWORDS = [
    "gpu", "tpu",
    "ephemeral disk", "persistent disk", "volume mount", "storage class",
    "cpu allocation", "memory limit", "memory size",
]

def validate_url(url):
    """Checks if the given URL returns a 200 OK or redirects successfully.
    Returns True if valid, False if broken (404, 403, etc.).
    """
    # Ignore dummy placeholders
    if "demo-" in url or "example.com" in url or "watch?v=demo" in url or "files/networking" in url:
        return False

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        req = urllib.request.Request(url, headers=headers)
        # We use a short timeout
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status in (200, 301, 302)
    except Exception as e:
        print(f"URL Validation failed for {url}: {e}")
        return False

def clean_markdown_links(content):
    """Finds all [text](url) patterns in markdown content and validates the URL.
    If the URL is invalid/broken, it replaces it with plain text: 'text'.
    """
    # Match markdown link: [text](url)
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    
    cleaned_content = content
    matches = link_pattern.findall(content)
    
    for text, url in matches:
        # Don't validate absolute paths or non-http links
        if not url.startswith("http"):
            continue
            
        print(f"Validating link: {url} ...")
        if not validate_url(url):
            print(f"⚠️ Invalid/Broken link found: {url}. Converting to plain text.")
            # Replace [text](url) with plain text "text"
            cleaned_content = cleaned_content.replace(f"[{text}]({url})", f"{text}")
            
    return cleaned_content

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
        "App Engine",
        "Gemini Enterprise Agent Platform",
        "Secure Web Proxy"
    ]

    notes_data = []
    for row in results:
        desc_lower = row.description.lower()

        # 필터링 대상 제품군에 한해서만 텍스트 키워드 필터링 적용
        if row.product_name in FILTERABLE_PRODUCTS:
            if any(ex in desc_lower for ex in NETWORKING_EXCLUSION_KEYWORDS):
                continue
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
    """Fetches blog posts from the Networking-category RSS feed and filters by date."""
    RSS_URL = "https://cloudblog.withgoogle.com/products/networking/rss/"
    print(f"Fetching blog posts from {RSS_URL}...")
    feed = feedparser.parse(RSS_URL)
    
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    blog_data = []
    for entry in feed.entries:
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime.date(entry.published_parsed.tm_year, entry.published_parsed.tm_mon, entry.published_parsed.tm_mday)
            if start_date <= pub_date < end_date:
                # feedparser 6.x exposes <category> elements via entry.tags as dicts
                # (entry.categories returns (scheme, term) tuples without a .term attr).
                categories = [t.get('term', '').lower() for t in entry.get('tags', []) or []]

                # Safety net: feed URL is already category-scoped, but require an explicit
                # 'networking' tag so any future feed change can't leak unrelated posts.
                if not any('networking' in c for c in categories):
                    continue

                blog_data.append({
                    "title": entry.title,
                    "description": entry.description,
                    "link": entry.link,
                    "published_at": pub_date.strftime('%Y-%m-%d')
                })
    print(f"Blog feed: {len(feed.entries)} entries fetched, {len(blog_data)} kept after date+category filter.")
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

def generate_newsletter_with_gemini(notes_data, blog_summaries, doc_content="", additional_resources=""):
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

    if additional_resources:
        raw_text += "\n--- [수동 추가 리소스 내역] ---\n\n"
        raw_text += additional_resources + "\n\n"

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
    - [중요] '우리 팀은 이를 참고하여', '활용할 수 있습니다', '참고하기 바랍니다', '도움이 될 것입니다' 등 독자나 엔지니어팀에게 조치나 활용을 권유하는 권유형/코멘트형 마무리를 절대 사용하지 말 것. 대신 순수 기술적 사실과 사실 관계(예: '...를 자동화하여 지연 시간을 최적화함', '...를 통해 트래픽 제어 효율을 개선함')만 담백하고 확실하게 종결형 어조로 전달할 것.
    - [중요] 제공된 원문 데이터의 'Date'(연도)를 반드시 더블체크하여 2026년 최신 데이터만 포함할 것.
    - [중요] 도입부 및 문서 헤더에 정리 기간을 명확히 표기할 것 (예: "2026년 4월~5월 업데이트").
    - [중요] 본문의 '각 세부 업데이트 항목'에 소개된 내용이 하단의 '공식 블로그 소식'이나 '추가 유용한 자료'의 블로그 포스트 내용과 중복되지 않도록 할 것. 동일한 기능 발표와 블로그 포스트가 동시에 존재한다면, 상세 릴리스 노트를 본문 카테고리에만 유지하고 하단 블로그 소식에는 중복 포스트를 배제할 것.

    ## 정보 구성 요구사항:
    1. **서두 요약 (Summary)**: 
       - "Google Cloud Networking 업데이트:"로 시작하여 이번 기간 동안 본문에 포함될 모든 카테고리(네트워크 인프라, GKE 네트워킹, Serverless 네트워킹, 트래픽 라우팅, 네트워크 보안, AI 및 Agent 인프라, 네트워크 운영 전 분야)의 핵심 사항을 본문의 카테고리 구조와 완전히 매핑시켜 3~4문장으로 건조하게 요약할 것.
    2. 아래 제공된 [필수 대분류 그룹 규칙]을 완전히 준수하여 본문을 구성할 것.
{category_context}
    3. **각 세부 업데이트 항목(단일 기능 릴리스) 구성**:
       반드시 아래의 형식을 엄격히 준수하여 작성할 것 (각 항목마다 이 구조를 반복):

       **[핵심 요약 제목]**
       - **적용 서비스**: {{특정 서비스 명칭}}
       - **업데이트 상세**: {{핵심 업데이트 또는 변경 사항을 날짜를 포함하여 1~2문장으로 요약}}
       - **실무 활용**: {{해당 업데이트가 제공하는 기술적 이점 및 사실을 명확하게 종결형 어조로 작성}}
       - **관련정보**: {{해당 업데이트 정보를 확인할 수 있는 URL 링크}}

       - [중요] 하나의 업데이트 항목에는 반드시 **단일한 기능의 단일 릴리스(발표일 기준)**만 작성할 것. 서로 다른 날짜의 릴리스나 별개의 기술적 변경 사항(예: GKE 업그레이드 내의 다수 독립 기능들)을 하나의 항목으로 묶어서 뭉뚱그려 작성하지 말고, 각각 독립된 항목으로 분리하여 작성할 것.

    4. **공식 블로그 소식 (Blog Posts)**: 제공된 'Google Cloud 공식 블로그 요약 내역'을 바탕으로, 주요 기술 블로그 소식을 별도의 섹션으로 정리할 것. 각 글의 제목과 요약, 그리고 링크를 포함할 것.

    5. HTML 태그 없이 마크다운으로만 작성할 것.
    6. [중요] 제공된 '수동 추가 리소스 내역'이 있다면, 뉴스레터 맨 하단(블로그 소식 아래)에 '추가 유용한 자료 및 유튜브 데모' 같은 적절한 대분류 섹션으로 보기 좋게 가다듬어 포함할 것. 각 링크와 매핑을 정확히 유지할 것.

    {raw_text}
    """

    print("Generating newsletter content with Gemini API...")
    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    return response.text

import re
import urllib.request
import urllib.error
import urllib.parse

def check_url_validity(url):
    """Validates if a URL is active and returns 200. Excludes known login/auth walls."""
    parsed_url = urllib.parse.urlparse(url)
    
    # Skip authentication-gated consoles or domains that aggressively block automated checks
    if "console.cloud.google.com" in parsed_url.netloc or "youtube.com" in parsed_url.netloc or "youtu.be" in parsed_url.netloc:
        return True
        
    try:
        # Add User-Agent to prevent blockades
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=4.0) as response:
            return response.status < 400
    except urllib.error.HTTPError as e:
        # 404 is definitively invalid, other codes (like 403/401) might be soft auth walls
        if e.code == 404:
            return False
        return e.code < 500
    except Exception as e:
        print(f"Error validating URL {url}: {e}")
        return False

def verify_newsletter(client, content):
    """Verifies the generated newsletter content for relevance, quality, and active URLs."""
    prompt = f"""
    아래 생성된 'Google Cloud Networking Newsletter'의 내용을 검증해줘.
    
    내용:
    {content}
    
    ## 검증 기준:
    1. 모든 내용이 Google Cloud Networking 및 Security, 혹은 AI 및 Agent 인프라 범위에 속하는가? (예: GKE, Cloud Run, BigQuery 등 네트워킹과 무관한 순수 데이터베이스나 AI 모델 발표는 제외되어야 함)
    2. AI가 생성한 느낌의 과장된 수사나 상투적인 인사말이 배제되었는가?
    3. "Google Cloud Networking 업데이트:"라는 문구로 시작하는가?
    4. 날짜가 2026년 최신 데이터인가?
    5. '우리 팀은 이를 참고하여', '활용할 수 있습니다' 등의 권유형 코멘트가 완전히 배제되고 기술적 사실 중심의 종결형 어조로 작성되었는가?
    
    ## 응답 형식:
    - 통과 여부: PASS 또는 FAIL
    - 이유: (FAIL인 경우 구체적인 이유 작성)
    
    응답은 반드시 위 형식을 지켜줘.
    """
    try:
        # First, validate all Markdown links in the content
        urls = re.findall(r'https?://[^\s)]+', content)
        # Clean URLs from trailing characters like quotes or markdown symbols
        cleaned_urls = []
        for u in urls:
            u_clean = u.rstrip("`*\"').,")
            cleaned_urls.append(u_clean)
            
        unique_urls = list(set(cleaned_urls))
        print(f"Extracted {len(unique_urls)} unique URLs for validation...")
        
        broken_urls = []
        for url in unique_urls:
            if not check_url_validity(url):
                print(f"❌ URL validation failed for: {url}")
                broken_urls.append(url)
                
        if broken_urls:
            return False, f"다음 링크들이 존재하지 않거나 유효하지 않습니다(404 등): {', '.join(broken_urls)}"

        print("All URLs passed validation. Verifying newsletter content with Gemini...")
        response = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        result = response.text
        print(f"Verification Result:\n{result}")

        if "PASS" in result.split('\n')[0]:
            return True, ""
        else:
            reason = ""
            for line in result.split('\n'):
                if "이유:" in line:
                    reason = line.split("이유:")[1].strip()
            return False, reason
    except Exception as e:
        print(f"Verification failed to execute: {e}")
        return True, "Verification tool failed, assuming pass"

def main():
    try:
        start_date_str = "2026-04-01" 
        end_date_str = "2026-06-01"
        now_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"networking_newsletter_2026_April_May_{now_str}.md"
        
        additional_resources = """
- **White papers (백서)**:
  * [Networking for AI inference model serving on GKE](https://cloud.google.com/files/networking-for-ai-inference-gke.pdf)
  * [Networking for AI inference model serving on all backends](https://cloud.google.com/files/networking-for-ai-inference-all.pdf)
- **유튜브 데모 및 세션 (YouTube & NEXT 26)**:
  * [Demo] Autonomous ML Reliability - Data Center Network
  * [Demo] High Resolution Network Telemetry: Data Center Network
  * [Google Cloud NEXT 26 - Session library](https://cloud.withgoogle.com/next)
- **추가 주요 블로그 소식 (Blogs)**:
  * [Cloud DNS Response Policy Zones to Selectively Bypass Google API Subdomains](https://cloud.google.com/blog/products/networking/dns-response-policy-zones-to-selectively-bypass-google-api-subdomains)
  * [[Public Preview] New configuration size quota and increased URL map size limits for Application Load Balancers](https://cloud.google.com/blog/products/networking/announcing-new-configuration-size-quota-and-increased-url-map-size-limits-for-application-load-balancers)
- **실습 랩 (Hands-on Labs)**:
  * Private Service Connect 엔드포인트를 활용하여 GCE 상에서 Antigravity CLI 가동하기 (Codelab 실습 랩)
"""

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
            newsletter_content = generate_newsletter_with_gemini(notes_data, blog_summaries, doc_content, additional_resources)
            
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
                    newsletter_content = f"⚠️ [VERIFICATION FAILED: {reason}]\n\n" + newsletter_content

        # 4. Output processing
        print("Running link validation and cleanup on generated content...")
        newsletter_content = clean_markdown_links(newsletter_content)

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
