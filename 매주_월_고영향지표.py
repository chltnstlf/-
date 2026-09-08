import datetime
import os
import requests
from google import genai
from google.genai import types

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def generate_report_with_gemini():
    """Gemini AI가 실시간 구글 검색으로 이번 주/다음 주 지표를 수집 및 분석"""
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY가 설정되지 않았습니다."

    client = genai.Client(api_key=GEMINI_API_KEY)
    today = datetime.date.today().strftime("%Y년 %m월 %d일")

    prompt = f"""
오늘 날짜({today}) 기준으로 실시간 구글 검색을 수행하여, 미국 경제 지표 발표 일정을 수집하고 심층 시장 분석 리포트를 작성하라.

[수집 및 분석 가이드라인]
1. 구글 검색을 통해 오늘 기준 '이번 주'와 '다음 주' 발표되는 미국의 핵심 경제 지표(CPI, PPI, PCE, FOMC, 비농업 고용, GDP, ISM 등)의 날짜/시간(한국시간 기준)과 지표명을 찾아라.
2. 각 지표의 시장 영향력에 따라 중요도 별표(⭐⭐⭐: 최상, ⭐⭐: 상, ⭐: 중)를 붙여 정리하라.
3. 수집된 일정을 바탕으로 지표 간의 연쇄 파급력을 계산하여 아래 3가지 카테고리로 나누어 입체적으로 분석하라:
   - 💡 **[시장 전반 & 통화정책]**: 국채금리, 달러 인덱스, 연준 금리 경로 관점
   - 🟡 **[금 & 금 채굴주(GDXU) 관점]**: 실질금리, 유동성, 3배 레버리지 변동성 대응 타점
   - 💻 **[반도체 & 빅테크(SOXX/SOXL 및 관련주) 관점]**: 금리/할인율, AI CapEx, 전방 IT 수요 파급력

[출력 포맷]
📊 **[주간 미국 핵심 경제 일정 & Gemini AI 브리핑]**
📅 기준일: {today}

🔥 **이번 주 주요 지표 (Critical Events)**
• [날짜 시각] 지표명 (중요도)

🚀 **다음 주 주요 지표 (Upcoming Events)**
• [날짜 시각] 지표명 (중요도)

💡 **[시장 전반 & 통화정책]**
- 내용...

🟡 **[금 & 금 채굴주(GDXU) 관점]**
- 내용...

💻 **[반도체 & 빅테크(SOXX/NVDA) 관점]**
- 내용...

[주의사항]
- 불필요한 서론, 결론, 인사말은 배제하고 위 마크다운 포맷 그대로 출력할 것.
"""

    try:
        # gemini-3.6-flash 최신 모델 적용
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        return response.text
    except Exception as e:
        return f"⚠️ Gemini AI 호출 및 검색 실패: {e}"


def send_telegram_message(token, chat_id, text):
    """텔레그램 메시지 전송"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    return res.json()


if __name__ == "__main__":
    report = generate_report_with_gemini()
    send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, report)
