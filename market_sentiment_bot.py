"""
미국주식 5대 심리지표 + SOXL / TQQQ / GDXU 5대 반등 조건 체크리스트 & 실시간 자동 감지 봇
- KST(한국시간) & NY(미국 뉴욕시간) 서머타임 자동 계산 및 장 상태 표기
- 장중 10분 주기 실시간 무소음 감시 (과대낙폭 감지시에만 긴급 알림)
- 4대 장 전환 시점(프리/본장/애프터 시작/마감) 정기 종합 브리핑 무조건 발송
"""

import os
import json
import time
import requests
import yfinance as yf
import datetime as dt
from zoneinfo import ZoneInfo

# ------------------------------------------------------------------
# 1. 설정값 및 시간대 설정
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

KST_TZ = ZoneInfo("Asia/Seoul")
NY_TZ  = ZoneInfo("America/New_York")

# ------------------------------------------------------------------
# 2. 시간 및 장 상태 판정 함수
# ------------------------------------------------------------------
def get_market_status_info():
    now_kst = dt.datetime.now(KST_TZ)
    now_ny = dt.datetime.now(NY_TZ)

    kst_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    ny_time_str = now_ny.strftime("%H:%M:%S")
    tz_name = now_ny.strftime("%Z") # EDT or EST

    weekday = now_ny.weekday() # 0:월 ~ 4:금, 5:토, 6:일
    ny_hour = now_ny.hour
    ny_minute = now_ny.minute
    ny_time_num = ny_hour * 100 + ny_minute

    # 주말 처리
    if weekday >= 5:
        status_text = "미국 주말 휴장"
        is_market_open = False
        session_code = "CLOSED"
    else:
        # 평일 장 상태 판정 (미국 동부 시간 기준)
        if 400 <= ny_time_num < 930:
            status_text = "미국 프리마켓 진행 중"
            is_market_open = True
            session_code = "PRE"
        elif 930 <= ny_time_num < 1600:
            status_text = "미국 정규장(본장) 진행 중"
            is_market_open = True
            session_code = "REGULAR"
        elif 1600 <= ny_time_num < 2000:
            status_text = "미국 애프터마켓 진행 중"
            is_market_open = True
            session_code = "AFTER"
        else:
            status_text = "미국 장외/휴장 시간"
            is_market_open = False
            session_code = "CLOSED"

    header_time_str = f"🕒 {kst_str} [{status_text} | 현지 {ny_time_str} {tz_name}]"
    return {
        "header_time_str": header_time_str,
        "is_market_open": is_market_open,
        "session_code": session_code,
        "ny_time_num": ny_time_num,
        "weekday": weekday
    }

# ------------------------------------------------------------------
# 3. 시장 심리지표 수집 함수
# ------------------------------------------------------------------
def get_cnn_fear_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        fg_score = data["fear_and_greed"]["score"]
        putcall_score = data["put_call_options"]["score"]
        return round(fg_score, 1), round(putcall_score, 1)
    except Exception as e:
        print(f"CNN 지표 수집 실패: {e}")
        return None, None

def get_vix():
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        return round(hist["Close"].iloc[-1], 2)
    except Exception as e:
        print(f"VIX 수집 실패: {e}")
        return None

def get_spy_rsi(period=14):
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(period="3mo")["Close"]
        delta = hist.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 1)
    except Exception as e:
        print(f"SPY RSI 수집 실패: {e}")
        return None

def get_aaii_sentiment():
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(base_path, "aaii_data.json")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bullish = float(data.get("bullish", 0))
        neutral = float(data.get("neutral", 0))
        bearish = float(data.get("bearish", 0))
        return bullish, neutral, bearish
    except Exception as e:
        print(f"aaii_data.json 읽기 실패: {e}")
        return None, None, None

# ------------------------------------------------------------------
# 4. 개별 레버리지 종목 5대 조건 정밀 분석 함수
# ------------------------------------------------------------------
def analyze_etf(ticker_symbol, vix_value):
    try:
        ticker = yf.Ticker(ticker_symbol)
        # 프리/애프터 마켓 가격 포함 수집
        df = ticker.history(period="1y", prepost=True)
        if df.empty or len(df) < 50:
            return None

        current_price = round(df["Close"].iloc[-1], 2)
        prev_close = df["Close"].iloc[-2]
        daily_change = round(((current_price - prev_close) / prev_close) * 100, 2)

        high_20d = df["High"].tail(20).max()
        drop_from_high = round(((current_price - high_20d) / high_20d) * 100, 1)

        # 1) 거래량 체크
        vol_today = df["Volume"].iloc[-1]
        vol_20ma = df["Volume"].tail(20).mean()
        vol_ratio = round(vol_today / vol_20ma, 1) if vol_20ma > 0 else 0
        cond_volume = vol_ratio >= 1.5

        # 2) 지지선 중첩 체크
        sma20 = df["Close"].rolling(window=20).mean().iloc[-1]
        std20 = df["Close"].rolling(window=20).std().iloc[-1]
        bb_lower = round(sma20 - (2 * std20), 2)

        sma50 = df["Close"].rolling(window=50).mean().iloc[-1]
        sma200 = df["Close"].rolling(window=200).mean().iloc[-1] if len(df) >= 200 else None

        near_sma50 = abs(current_price - sma50) / sma50 <= 0.03
        near_sma200 = (abs(current_price - sma200) / sma200 <= 0.03) if sma200 else False
        is_bb_break = current_price <= bb_lower

        cond_support = is_bb_break or near_sma50 or near_sma200

        # 3) VIX & 5일 이격도 체크
        sma5 = df["Close"].rolling(window=5).mean().iloc[-1]
        disparity_5d = round((current_price / sma5) * 100, 1)
        cond_vix_disparity = (vix_value is not None and vix_value >= 25) or (disparity_5d <= 92.0)

        # 4) 아래꼬리 반등 / RSI 체크
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1)

        day_low = df["Low"].iloc[-1]
        rebound_from_low = round(((current_price - day_low) / day_low) * 100, 1) if day_low > 0 else 0
        cond_rebound = (rsi <= 35) or (rebound_from_low >= 1.5)

        # 5) 전일 대비 -7% 이상 급락 여부
        cond_daily_plunge = daily_change <= -7.0

        checklist = [
            ("1. 전일대비 급락", cond_daily_plunge, f"{daily_change}% 하락"),
            ("2. 거래량 폭발", cond_volume, f"평소 대비 {vol_ratio}배"),
            ("3. 지지선 중첩", cond_support, f"볼린저하단 ${bb_lower}" if is_bb_break else "주요 이평선 근접"),
            ("4. 이격도/VIX 공포", cond_vix_disparity, f"5일 이격 {disparity_5d}% / VIX {vix_value}"),
            ("5. 반등/RSI 과매도", cond_rebound, f"RSI {rsi} / 저점대비 +{rebound_from_low}%")
        ]

        score = sum(1 for _, is_met, _ in checklist if is_met)

        p1 = current_price
        p2 = round(p1 * 0.93, 2)
        p3 = round(p1 * 0.85, 2)
        p4 = round(p1 * 0.75, 2)

        buy_plan = (
            f"💼 <b>[{ticker_symbol} 500만 원 분할 매수 타점]</b>\n"
            f"├ <b>1차 (150만/30%)</b> : <code>${p1}</code> (현재가 진입)\n"
            f"├ <b>2차 (150만/30%)</b> : <code>${p2}</code> (-7% 추가하락)\n"
            f"├ <b>3차 (100만/20%)</b> : <code>${p3}</code> (-15% 추가하락)\n"
            f"└ <b>4차 (100만/20%)</b> : <code>${p4}</code> (-25% 패닉셀ing)"
        )

        return {
            "symbol": ticker_symbol,
            "price": current_price,
            "daily_change": daily_change,
            "drop_from_high": drop_from_high,
            "rsi": rsi,
            "score": score,
            "checklist": checklist,
            "buy_plan": buy_plan,
            "is_triggered": (score >= 3 or cond_daily_plunge) # 매수 신호 발동 여부
        }
    except Exception as e:
        print(f"{ticker_symbol} 데이터 분석 실패: {e}")
        return None

def format_etf_section(data):
    if not data:
        return "⚠️ 데이터 수집 실패"

    sym = data["symbol"]
    p = data["price"]
    chg = data["daily_change"]
    drop = data["drop_from_high"]
    score = data["score"]
    checklist = data["checklist"]
    plan = data["buy_plan"]
    is_triggered = data["is_triggered"]

    chg_icon = "🔺" if chg > 0 else "🔻"
    chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"
    drop_emoji = "🟢" if drop <= -20.0 else "⚪"

    checklist_lines = []
    for title, is_met, detail in checklist:
        mark = "[✅]" if is_met else "[❌]"
        checklist_lines.append(f" {mark} <b>{title}</b> ({detail})")
    checklist_text = "\n".join(checklist_lines)

    metrics_text = (
        f"• <b>현재가:</b> <code>${p}</code> ({chg_icon} {chg_str})\n"
        f"• <b>20일 고점 대비:</b> {drop_emoji} {drop}%\n\n"
        f"📋 <b>[10% 반등 5대 필승 체크리스트]</b>\n"
        f"{checklist_text}"
    )

    stars = "🔥" * score + "⚪" * (5 - score)

    if is_triggered:
        return (
            f"🚨 <b>[{sym} 매수 추천 구간]</b> - {stars} ({score}/5개 충족)\n"
            f"{metrics_text}\n\n"
            f"{plan}"
        )
    elif score == 2:
        return (
            f"⚠️ <b>[{sym} 관심 관찰 구간]</b> - {stars} ({score}/5개 충족)\n"
            f"{metrics_text}"
        )
    else:
        return (
            f"📊 <b>[{sym} 정상/관망 구간]</b> - {stars} ({score}/5개 충족)\n"
            f"{metrics_text}"
        )

# ------------------------------------------------------------------
# 5. 시장 판정 및 리포트 생성 함수
# ------------------------------------------------------------------
def judge_fear_greed(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🟢 <b>{score}</b> (극단적 공포)"
    if score >= 75: return f"🔴 <b>{score}</b> (극단적 탐욕)"
    return f"⚪ <b>{score}</b> (중립~보통)"

def judge_putcall(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🔴 <b>{score}</b> (콜 쏠림)"
    if score >= 75: return f"🟢 <b>{score}</b> (풋 쏠림)"
    return f"⚪ <b>{score}</b> (중립)"

def judge_vix(vix):
    if vix is None: return "⚪ 데이터 없음"
    if vix >= 40: return f"🟢 <b>{vix}</b> (패닉/급등)"
    if vix <= 13: return f"🔴 <b>{vix}</b> (과열 점검)"
    return f"⚪ <b>{vix}</b> (평온~경계)"

def judge_rsi(rsi):
    if rsi is None: return "⚪ 데이터 없음"
    if rsi <= 30: return f"🟢 <b>{rsi}</b> (과매도)"
    if rsi >= 70: return f"🔴 <b>{rsi}</b> (과매수)"
    return f"⚪ <b>{rsi}</b> (중립)"

def judge_aaii(bullish, neutral, bearish):
    if bearish is None or bullish is None: return "⚪ 데이터 없음"
    msg = f"Bull {bullish}% / Bear {bearish}%"
    if bearish >= 50: return f"🟢 <b>{msg}</b> (Bearish 50%↑ 역발상 매수)"
    if bullish >= 50: return f"🔴 <b>{msg}</b> (Bullish 50%↑ 과열)"
    return f"⚪ <b>{msg}</b> (중립)"

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=payload, timeout=10)

def generate_and_send_report(briefing_title=None, force_send=False):
    status_info = get_market_status_info()
    header_time_str = status_info["header_time_str"]

    fg_score, putcall_score = get_cnn_fear_greed()
    vix = get_vix()
    rsi = get_spy_rsi()
    bullish, neutral, bearish = get_aaii_sentiment()

    soxl_data = analyze_etf("SOXL", vix)
    tqqq_data = analyze_etf("TQQQ", vix)
    gdxu_data = analyze_etf("GDXU", vix)

    # 매수 신호가 발생한 종목이 하나라도 있는지 확인
    any_triggered = any([
        soxl_data and soxl_data.get("is_triggered"),
        tqqq_data and tqqq_data.get("is_triggered"),
        gdxu_data and gdxu_data.get("is_triggered")
    ])

    # 조건부 전송 제어: 정기 브리핑이거나(force_send=True) 매수 추천 신호가 떴을 때만 전송
    if not force_send and not any_triggered:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 관망 구간 - 텔레그램 메시지 전송 안 함 (무소음 감시 중)")
        return

    title_header = f"📢 <b>[{briefing_title}]</b>\n" if briefing_title else "📈 <b>미국주식 심리지표 & 레버리지 리포트</b>\n"

    lines = [
        title_header,
        header_time_str,
        "━━━━━━━━━━━━━━━━━━━━",
        f"<b>1. CNN 공포탐욕지수:</b> {judge_fear_greed(fg_score)}",
        f"<b>2. Put/Call Ratio:</b> {judge_putcall(putcall_score)}",
        f"<b>3. CBOE VIX:</b> {judge_vix(vix)}",
        f"<b>4. AAII 심리지수:</b> {judge_aaii(bullish, neutral, bearish)}",
        f"<b>5. S&P500 RSI:</b> {judge_rsi(rsi)}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 <b>[SOXL 분석]</b>",
        format_etf_section(soxl_data),
        "------------------------------------",
        f"📌 <b>[TQQQ 분석]</b>",
        format_etf_section(tqqq_data),
        "------------------------------------",
        f"📌 <b>[GDXU 분석]</b>",
        format_etf_section(gdxu_data)
    ]

    message = "\n".join(lines)
    send_telegram(message)
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 텔레그램 리포트 전송 완료!")

# ------------------------------------------------------------------
# 6. GitHub Actions (1회 실행) 및 내 PC (24시간 실행) 통합 실행부
# ------------------------------------------------------------------
def run_once():
    """GitHub Actions 전용: 15분마다 깃허브가 켜져서 1회 감시만 수행하고 종료되는 함수"""
    status_info = get_market_status_info()
    ny_time_num = status_info["ny_time_num"]
    weekday = status_info["weekday"]

    briefing_type = None

    # 평일일 때 4대 주요 장 전환 시점 정기 브리핑 판정 (15분 간격에 맞게 감지)
    if weekday < 5:
        if 400 <= ny_time_num < 415:
            briefing_type = "미국 프리마켓 개장 브리핑"
        elif 930 <= ny_time_num < 945:
            briefing_type = "미국 정규장(본장) 개장 브리핑"
        elif 1600 <= ny_time_num < 1615:
            briefing_type = "미국 정규장 마감 / 애프터마켓 개장 브리핑"
        elif 2000 <= ny_time_num < 2015:
            briefing_type = "미국 애프터마켓 마감 브리핑"

    if briefing_type:
        # 정기 브리핑 시점이면 무조건 브리핑 전송
        generate_and_send_report(briefing_title=briefing_type, force_send=True)
    elif status_info["is_market_open"]:
        # 장중(프리/본장/애프터)일 때만 과대낙폭 조건 감시 (조건 미충족 시 무소음/무전송)
        generate_and_send_report(force_send=False)
    else:
        print("미국 장외/휴장 시간입니다. (무소음 대기)")

def main_loop():
    """내 컴퓨터 전용: PC를 켜두고 24시간 계속 돌릴 때 사용하는 무한 루프 함수"""
    print("🚀 레버리지 과대낙폭 감시 봇이 시작되었습니다.")
    
    try:
        print("📢 봇 실행 확인: 작동 점검 리포트를 텔레그램으로 전송합니다...")
        generate_and_send_report(briefing_title="🤖 봇 시작 / 시스템 작동 점검 리포트", force_send=True)
    except Exception as e:
        print(f"시작 점검 메시지 전송 실패: {e}")

    last_briefing_session = None

    while True:
        try:
            status_info = get_market_status_info()
            ny_time_num = status_info["ny_time_num"]
            weekday = status_info["weekday"]

            briefing_type = None
            if weekday < 5:
                if 400 <= ny_time_num < 410 and last_briefing_session != "PRE_OPEN":
                    briefing_type = "미국 프리마켓 개장 브리핑"
                    last_briefing_session = "PRE_OPEN"
                elif 930 <= ny_time_num < 940 and last_briefing_session != "REGULAR_OPEN":
                    briefing_type = "미국 정규장(본장) 개장 브리핑"
                    last_briefing_session = "REGULAR_OPEN"
                elif 1600 <= ny_time_num < 1610 and last_briefing_session != "AFTER_OPEN":
                    briefing_type = "미국 정규장 마감 / 애프터마켓 개장 브리핑"
                    last_briefing_session = "AFTER_OPEN"
                elif 2000 <= ny_time_num < 2010 and last_briefing_session != "AFTER_CLOSE":
                    briefing_type = "미국 애프터마켓 마감 브리핑"
                    last_briefing_session = "AFTER_CLOSE"

            if briefing_type:
                generate_and_send_report(briefing_title=briefing_type, force_send=True)
            elif status_info["is_market_open"]:
                generate_and_send_report(force_send=False)

        except Exception as e:
            print(f"메인 루프 에러 발생: {e}")

        time.sleep(600)

if __name__ == "__main__":
    # 💡 깃허브 액션으로 동작할 때 (RUN_ONCE 환경변수가 true일 때)
    if os.environ.get("RUN_ONCE") == "true":
        run_once()
    # 💡 내 PC에서 직접 'python market_sentiment_bot.py'로 켰을 때
    else:
        main_loop()
