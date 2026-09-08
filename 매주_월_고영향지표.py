import datetime
import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # OpenAI API 키


def get_economic_calendar():
    """ForexFactory 주간 데이터 수집"""
    url = "https://nfs.forexfactory.net/5min/api/calendar/thisWeek.json"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[ERROR] 데이터 수신 실패: {e}")
    return []


def parse_high_impact_events(events):
    """USD 고영향 지표 추출 및 포맷팅"""
    high_events = []
    event_summary_for_ai = []

    for event in events:
        currency = str(event.get("currency", "")).upper()
        country = str(event.get("country", "")).upper()
        impact = str(event.get("impact", "")).capitalize()

        if (currency == "USD" or country == "USD") and impact == "High":
            title = event.get("title", "")
            date_str = event.get("date", "")
            time_str = event.get("time", "")
            forecast = event.get("forecast", "N/A")
            previous = event.get("previous", "N/A")

            try:
                dt = datetime.datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                )
                formatted_date = dt.strftime("%m/%d(%a)")
            except Exception:
                formatted_date = date_str[:10]

            high_events.append(f"• **{formatted_date} {time_str}**: {title}")
            event_summary_for_ai.append(
                f"- {formatted_date} {time_str} | 지표명: {title} | 예측치:"
                f" {forecast} | 이전치: {previous}"
            )

    return high_events, "\n".join(event_summary_for_ai)


def analyze_with_ai(event_text_for_ai):
    """LLM(GPT)이 스스로 입체를 판단하여 매크로, 금, 반도체 영향을 종합 분석"""
    if not OPENAI_API_KEY:
        return (
            "⚠️ OPENAI_API_KEY가 설정되지 않아 AI 심층 분석을 생략합니다."
        )

    if not event_text_for_ai:
        return "💡 **[AI 시황 관전 포인트]**\n이번 주는 주요 매크로 지표 발표가 없는 주간입니다. 기술적 수급 및 지경학적 변수에 주목하세요."

    prompt = f"""
너는 월가 최고 수준의 글로벌 매크로 및 반도체 섹터 전문 수석 애널리스트다.
아래 제공된 [이번 주 미국 주요 경제 지표 발표 일정]을 바탕으로, 시장을 다각도로 종합 분석하여 리포트를 작성해라.

[이번 주 주요 지표 일정]
{event_text_for_ai}

[작성 가이드라인]
1. 단순 지표 설명이 아니라, 지표들 간의 상호작용과 연준(Fed)의 정책 방향성에 미칠 파급력을 입체적으로 분석하라.
2. 다음 3가지 항목으로 나누어 텔레그램 메시지용 마크다운 형식으로 작성하라:

💡 **[시장 전반 & 통화정책]**
- 국채금리, 달러 인덱스, 연준 금리 경로 관점의 종합적 분석

🟡 **[금 & 금 채굴주(GDXU) 관점]**
- 실질금리, 유동성, 지표 수치에 따른 금 가격 및 3배 레버리지 채굴주(GDXU) 변동성 포인트

💻 **[반도체 & 빅테크(SOXX/NVDA) 관점]**
- 금리/물가/제조업 지표가 반도체 밸류에이션(할인율), AI 자본지출(CapEx), 전방 IT 수요에 미치는 다이렉트 영향

[주의]
- 불필요한 서론이나 인사말은 전부 배제하고 본론만 간결하고 명확하게 작성할 것.
- 텔레그램 마크다운 문법을 지킬 것.
"""

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",  # 가성비 및 속도가 뛰어난 모델 사용
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }

        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            result = res.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"⚠️ AI 분석 생성 실패 (HTTP {res.status_code})"
    except Exception as e:
        return f"⚠️ AI 분석 호출 중 오류 발생: {e}"


def send_telegram_message(token, chat_id, text):
    """텔레그램 메시지 전송"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    return res.json()


if __name__ == "__main__":
    raw_calendar = get_economic_calendar()
    formatted_events, event_text_for_ai = parse_high_impact_events(
        raw_calendar
    )

    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    event_list_text = (
        "\n".join(formatted_events)
        if formatted_events
        else "이번 주 예정된 미국 주요 지표가 없습니다."
    )

    # AI 심층 동적 분석 실행
    ai_analysis = analyze_with_ai(event_text_for_ai)

    message = (
        f"📊 **[주간 미국 핵심 경제 일정 & AI 심층 브리핑]**\n"
        f"📅 기준일: {today}\n\n"
        f"🔥 **이번 주 주요 지표 (High Impact)**\n"
        f"{event_list_text}\n\n"
        f"{ai_analysis}"
    )

    send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
