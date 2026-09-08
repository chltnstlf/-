import datetime
import requests
import os

# 1. 텔레그램 설정 (본인의 토큰과 Chat ID로 변경하세요)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "여기에_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "여기에_CHAT_ID_입력")


def get_economic_calendar():
    """ForexFactory 주간 데이터 가져오기 (무료 API 피드)"""
    url = "https://nfs.forexfactory.net/5min/api/calendar/thisWeek.json"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"데이터 수신 실패: {e}")

    return []


def parse_high_impact_events(events):
    """USD 관련 High Impact(주요) 경제 이벤트만 추출"""
    high_events = []

    for event in events:
        # 미국(USD) 및 고영향(High) 이벤트만 필터링
        country = event.get("country", "")
        impact = event.get("impact", "")

        if country == "USD" and impact == "High":
            title = event.get("title", "")
            date_str = event.get("date", "")  # ISO 날짜
            time_str = event.get("time", "")  # 발표 시간

            # 날짜 및 시간 포맷 정리
            try:
                dt = datetime.datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                )
                formatted_date = dt.strftime("%m/%d(%a)")
            except Exception:
                formatted_date = date_str[:10]

            high_events.append(f"• **{formatted_date} {time_str}**: {title}")

    if not high_events:
        return "이번 주 예정된 미국 주요(High Impact) 경제 지표가 없습니다."

    return "\n".join(high_events)


def send_telegram_message(token, chat_id, text):
    """텔레그램 메시지 전송"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    return res.json()


if __name__ == "__main__":
    raw_events = get_economic_calendar()
    formatted_events = parse_high_impact_events(raw_events)

    today = datetime.date.today().strftime("%Y년 %m월 %d일")

    message = (
        f"📊 **[주간 미국 핵심 경제 일정 브리핑]**\n"
        f"📅 기준일: {today}\n\n"
        f"🔥 **이번 주 주요 지표 (High Impact)**\n"
        f"{formatted_events}\n\n"
        f"💡 *Tip: 주요 물가/고용 지표 발표 시 국채금리 및 금/GDXU 변동성이 확대되므로 대응에 주의하세요.*"
    )

    send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
