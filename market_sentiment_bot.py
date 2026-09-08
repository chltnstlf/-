"""
미국주식 5대 심리지표 + 주요 거시경제 지표(유가/환율/금리) 실시간 자동 감지 봇
- KST(한국시간) & NY(미국 뉴욕시간) 서머타임 자동 계산 및 장 상태 표기
- 5대 심리지표: CNN 공포탐욕지수, Put/Call Ratio, VIX, AAII 심리지수, SPY RSI
- 주요 거시경제: 브렌트유가, 엔/달러 환율, 미국 10년물 국채금리
- 깃허브 액션(15분 주기) & 개인/그룹 동시 전송 완벽 지원
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

    header_time_str = f"🕒 {kst_str}\n[{status_text} | 현지 {ny_time_str} {tz_name}]"
    return {
        "header_time_str": header_time_str,
        "is_market_open": is_market_open,
        "session_code": session_code,
        "ny_time_num": ny_time_num,
        "weekday": weekday
    }

# ------------------------------------------------------------------
# 3. 시장 심리지표 수집 함수 (5대 지표)
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
# 4. 거시경제 지표 수집 함수 (유가 / 환율 / 금리)
# ------------------------------------------------------------------
def get_brent_crude():
    """브렌트유 선물 (BZ=F) 수집"""
    try:
        ticker = yf.Ticker("BZ=F")
        hist = ticker.history(period="5d")
        if hist.empty: return None, None
        curr = round(hist["Close"].iloc[-1], 2)
        prev = hist["Close"].iloc[-2]
        chg = round(((curr - prev) / prev) * 100, 2)
        return curr, chg
    except Exception as e:
        print(f"브렌트유 수집 실패: {e}")
        return None, None

def get_usdjpy():
    """엔/달러 환율 (JPY=X) 수집"""
    try:
        ticker = yf.Ticker("JPY=X")
        hist = ticker.history(period="5d")
        if hist.empty: return None, None
        curr = round(hist["Close"].iloc[-1], 2)
        prev = hist["Close"].iloc[-2]
        chg = round(((curr - prev) / prev) * 100, 2)
        return curr, chg
    except Exception as e:
        print(f"엔/달러 수집 실패: {e}")
        return None, None

def get_us10y():
    """미국 10년물 국채금리 (^TNX) 수집"""
    try:
        ticker = yf.Ticker("^TNX")
        hist = ticker.history(period="5d")
        if hist.empty: return None, None
        raw_val = hist["Close"].iloc[-1]
        curr = round(raw_val / 10 if raw_val > 20 else raw_val, 2) # TNX 지수는 10배 표기되는 경우 보정
        prev_raw = hist["Close"].iloc[-2]
        prev = round(prev_raw / 10 if prev_raw > 20 else prev_raw, 2)
        chg_diff = round(curr - prev, 2) # 금리는 %p 차이로 표기
        return curr, chg_diff
    except Exception as e:
        print(f"10년물 국채금리 수집 실패: {e}")
        return None, None

# ------------------------------------------------------------------
# 5. 지표 판정 및 텔레그램 전송 함수
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

def format_macro_val(val, chg, unit="", is_bp=False):
    if val is None: return "⚪ 데이터 없음"
    icon = "🔺" if chg > 0 else "🔻" if chg < 0 else "➖"
    chg_str = f"+{chg}" if chg > 0 else f"{chg}"
    suffix = "%p" if is_bp else "%"
    return f"<code>{val}{unit}</code> ({icon} {chg_str}{suffix})"

def send_telegram(text: str):
    """개인 및 그룹 채팅방 쉼표(,) 구분 다중 수신 지원"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    
    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(",") if cid.strip()]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    for chat_id in chat_ids:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            print(f"텔레그램 전송 실패 ({chat_id}): {e}")

def generate_and_send_report(briefing_title=None):
    status_info = get_market_status_info()
    header_time_str = status_info["header_time_str"]

    # 1) 5대 심리지표 수집
    fg_score, putcall_score = get_cnn_fear_greed()
    vix = get_vix()
    rsi = get_spy_rsi()
    bullish, neutral, bearish = get_aaii_sentiment()

    # 2) 주요 거시경제 지표 수집
    brent_p, brent_c = get_brent_crude()
    jpy_p, jpy_c = get_usdjpy()
    tnx_p, tnx_c = get_us10y()

    title_header = f"📢 <b>[{briefing_title}]</b>\n" if briefing_title else "📈 <b>미국증시 심리 & 거시경제 실시간 리포트</b>\n"

    lines = [
        title_header,
        header_time_str,
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 <b>[미국주식 5대 심리지표]</b>",
        f"1. <b>CNN 공포탐욕지수:</b> {judge_fear_greed(fg_score)}",
        f"2. <b>Put/Call Ratio:</b> {judge_putcall(putcall_score)}",
        f"3. <b>CBOE VIX Index:</b> {judge_vix(vix)}",
        f"4. <b>AAII 심리지수:</b> {judge_aaii(bullish, neutral, bearish)}",
        f"5. <b>S&P500 RSI:</b> {judge_rsi(rsi)}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🌐 <b>[주요 거시경제 지표]</b>",
        f"🛢️ <b>브렌트유 (Brent):</b> {format_macro_val(brent_p, brent_c, '$')}",
        f"💴 <b>엔/달러 (USD/JPY):</b> {format_macro_val(jpy_p, jpy_c, '엔')}",
        f"💵 <b>미 10년물 국채금리:</b> {format_macro_val(tnx_p, tnx_c, '%', is_bp=True)}",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    message = "\n".join(lines)
    send_telegram(message)
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 텔레그램 리포트 전송 완료!")

# ------------------------------------------------------------------
# 6. GitHub Actions (1회 실행) 및 내 PC (24시간 실행) 통합 실행부
# ------------------------------------------------------------------
def run_once():
    """GitHub Actions 전용: 15분마다 켜져서 브리핑/정기 업데이트 수행 후 종료"""
    status_info = get_market_status_info()
    ny_time_num = status_info["ny_time_num"]
    weekday = status_info["weekday"]

    briefing_type = None

    # 평일일 때 4대 주요 장 전환 시점 정기 브리핑 이름 설정
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
        generate_and_send_report(briefing_title=briefing_type)
    else:
        # 15분마다 정기 모니터링 리포트 전송
        generate_and_send_report(briefing_title="15분 실시간 정기 업데이트")

def main_loop():
    """내 PC에서 직접 24시간 돌릴 때"""
    print("🚀 심리지표 & 거시경제 알림 봇이 시작되었습니다.")
    
    try:
        generate_and_send_report(briefing_title="🤖 시스템 시작 점검 리포트")
    except Exception as e:
        print(f"시작 점검 메시지 전송 실패: {e}")

    while True:
        try:
            generate_and_send_report(briefing_title="15분 실시간 정기 업데이트")
        except Exception as e:
            print(f"메인 루프 에러 발생: {e}")

        time.sleep(900) # 15분(900초)마다 대기

if __name__ == "__main__":
    if os.environ.get("RUN_ONCE") == "true":
        run_once()
    else:
        main_loop()
