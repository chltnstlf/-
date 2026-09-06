"""
미국주식 5대 심리지표 텔레그램 알림 봇
- CNN 공포탐욕지수 / Put-Call Ratio / CBOE VIX / AAII 심리지수 / S&P500 RSI
- 각 지표를 가이드북 기준값과 비교해 '공포/과열' 위치를 판정 후 텔레그램 전송

필요 패키지: pip install requests yfinance beautifulsoup4 schedule
"""

import os
import requests
import yfinance as yf
import datetime as dt

# ------------------------------------------------------------------
# 1. 설정값 - GitHub Actions에서는 Secrets를 환경변수로 주입합니다.
#    로컬 테스트 시에는 터미널에서 아래처럼 export 해두고 실행하세요.
#    export TELEGRAM_BOT_TOKEN="..."
#    export TELEGRAM_CHAT_ID="..."
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ------------------------------------------------------------------
# 2. 지표별 수집 함수
# ------------------------------------------------------------------
def get_cnn_fear_greed():
    """CNN 공포탐욕지수 + 하위지표(Put/Call 포함) 가져오기"""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()

    fg_score = data["fear_and_greed"]["score"]
    putcall_score = data["put_call_options"]["score"]  # 0~100 스케일 (CNN 정규화값)
    return round(fg_score, 1), round(putcall_score, 1)


def get_vix():
    """CBOE VIX 최신 종가"""
    vix = yf.Ticker("^VIX")
    hist = vix.history(period="5d")
    return round(hist["Close"].iloc[-1], 2)


def get_spy_rsi(period=14):
    """SPY 종가 기준 RSI(14) 계산 (Wilder 방식)"""
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


def get_aaii_sentiment():
    """AAII 주간 심리지수 (Bullish / Neutral / Bearish) 스크래핑
    주1회(목요일)만 갱신되며, 사이트 구조가 바뀌면 깨질 수 있음.
    실패 시 None 반환 -> 메시지에서 '데이터 없음' 처리
    """
    try:
        from bs4 import BeautifulSoup
        url = "https://www.aaii.com/sentimentsurvey"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # 사이트 구조가 자주 바뀌므로, 실제 값 추출 로직은
        # 페이지 소스를 열어서 직접 확인 후 selector를 맞춰야 합니다.
        # 아래는 예시 자리표시자입니다.
        bullish = None
        neutral = None
        bearish = None
        # TODO: 실제 셀렉터로 교체
        return bullish, neutral, bearish
    except Exception:
        return None, None, None


# ------------------------------------------------------------------
# 3. 판정 함수 (가이드북 기준값 적용)
# ------------------------------------------------------------------
def judge_fear_greed(score):
    if score is None:
        return "데이터 없음"
    if score <= 25:
        return f"{score} → 극단적 공포 (매수 점검 구간)"
    if score >= 75:
        return f"{score} → 극단적 탐욕 (과열 경계 구간)"
    return f"{score} → 중립~보통 범위"


def judge_putcall(score):
    # CNN이 제공하는 정규화 점수 기준 (0~100, 낮을수록 '탐욕/콜 우위')
    if score is None:
        return "데이터 없음"
    if score <= 25:
        return f"{score} → 콜 쏠림(과도한 낙관) 근접"
    if score >= 75:
        return f"{score} → 풋 쏠림(공포) 근접"
    return f"{score} → 중립 범위"


def judge_vix(vix):
    if vix >= 40:
        return f"{vix} → 40 이상, 패닉·급등 구간"
    if vix <= 13:
        return f"{vix} → 12~13대, 장기 저공비행(안일함 점검)"
    return f"{vix} → 평온~경계 범위"


def judge_rsi(rsi):
    if rsi <= 30:
        return f"{rsi} → 30 근접/이하, 과매도(공포)"
    if rsi >= 70:
        return f"{rsi} → 70 이상, 과매수(과열)"
    return f"{rsi} → 중립 범위"


def judge_aaii(bullish, neutral, bearish):
    if bearish is None:
        return "데이터 없음 (수집 로직 보완 필요)"
    msg = f"Bull {bullish}% / Neutral {neutral}% / Bear {bearish}%"
    if bearish >= 50:
        return f"{msg} → Bearish 50%↑ 역발상 매수 점검"
    if bullish >= 50:
        return f"{msg} → Bullish 50%↑ 과열 경계"
    return f"{msg} → 중립 범위"


# ------------------------------------------------------------------
# 4. 텔레그램 전송
# ------------------------------------------------------------------
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    r = requests.post(url, data=payload, timeout=10)
    r.raise_for_status()


# ------------------------------------------------------------------
# 5. 메인 실행
# ------------------------------------------------------------------
def run():
    today = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
        fg_score, putcall_score = get_cnn_fear_greed()
    except Exception as e:
        fg_score, putcall_score = None, None
        fg_err = str(e)

    try:
        vix = get_vix()
    except Exception:
        vix = None

    try:
        rsi = get_spy_rsi()
    except Exception:
        rsi = None

    bullish, neutral, bearish = get_aaii_sentiment()

    lines = [
        f"<b>미국주식 심리지표 알림</b> ({today})",
        "",
        f"1) CNN 공포탐욕지수: {judge_fear_greed(fg_score)}",
        f"2) Put/Call (CNN 하위지표): {judge_putcall(putcall_score)}",
        f"3) CBOE VIX: {judge_vix(vix) if vix else '데이터 없음'}",
        f"4) AAII 심리지수: {judge_aaii(bullish, neutral, bearish)}",
        f"5) S&P500(SPY) RSI: {judge_rsi(rsi) if rsi else '데이터 없음'}",
    ]
    message = "\n".join(lines)

    print(message)  # 로컬 로그 확인용
    send_telegram(message)


if __name__ == "__main__":
    run()
