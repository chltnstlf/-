"""
미국주식 5대 심리지표 텔레그램 알림 봇
- CNN 공포탐욕지수 / Put-Call Ratio / CBOE VIX / AAII 심리지수 / S&P500 RSI
- 각 지표를 가이드북 기준값과 비교해 '공포/과열' 위치를 판정 후 텔레그램 전송
"""

import os
import requests
import yfinance as yf
import datetime as dt

# ------------------------------------------------------------------
# 1. 설정값 - GitHub Actions Secrets 환경변수
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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


import pandas as pd

def get_aaii_sentiment():
    """
    AAII 공식 히스토리 엑셀 파일(sentiment.xls)을 직접 다운로드 및 파싱
    - 봇 차단 없이 주간 최신 수치(Bullish, Neutral, Bearish)를 정확히 가져옴
    """
    url = "https://www.aaii.com/files/surveys/sentiment.xls"
    
    try:
        # AAII 공식 sentiment.xls의 'SENTIMENT' 시트를 읽어옴
        # 상단 3행 헤더 스킵 처리
        df = pd.read_excel(url, sheet_name="SENTIMENT", skiprows=3)
        
        # 'Date' 열 또는 데이터가 있는 행들만 유효하게 필터링
        df = df.dropna(subset=['Bullish', 'Bearish'])
        
        if df.empty:
            return None, None, None
            
        # 가장 최근(마지막) 데이터 행 가져오기
        latest = df.iloc[-1]
        
        # 소수점 데이터(0.42 -> 42.0%) 퍼센티지로 변환
        bullish = round(float(latest['Bullish']) * 100, 1) if latest['Bullish'] < 1 else round(float(latest['Bullish']), 1)
        bearish = round(float(latest['Bearish']) * 100, 1) if latest['Bearish'] < 1 else round(float(latest['Bearish']), 1)
        
        # Neutral 값이 표에 없을 경우 100에서 차감하여 자동 계산
        if 'Neutral' in latest and pd.notna(latest['Neutral']):
            neutral = round(float(latest['Neutral']) * 100, 1) if latest['Neutral'] < 1 else round(float(latest['Neutral']), 1)
        else:
            neutral = round(100.0 - (bullish + bearish), 1)

        return bullish, neutral, bearish

    except Exception as e:
        print(f"AAII 엑셀 수집 중 에러 발생: {e}")
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
    if score is None:
        return "데이터 없음"
    if score <= 25:
        return f"{score} → 콜 쏠림(과도한 낙관) 근접"
    if score >= 75:
        return f"{score} → 풋 쏠림(공포) 근접"
    return f"{score} → 중립 범위"


def judge_vix(vix):
    if vix is None:
        return "데이터 없음"
    if vix >= 40:
        return f"{vix} → 40 이상, 패닉·급등 구간"
    if vix <= 13:
        return f"{vix} → 12~13대, 장기 저공비행(안일함 점검)"
    return f"{vix} → 평온~경계 범위"


def judge_rsi(rsi):
    if rsi is None:
        return "데이터 없음"
    if rsi <= 30:
        return f"{rsi} → 30 근접/이하, 과매도(공포)"
    if rsi >= 70:
        return f"{rsi} → 70 이상, 과매수(과열)"
    return f"{rsi} → 중립 범위"


def judge_aaii(bullish, neutral, bearish):
    if bearish is None or bullish is None:
        return "데이터 없음"
    
    spread = round(bullish - bearish, 1)
    msg = f"Bull {bullish}% / Neutral {neutral}% / Bear {bearish}%"
    
    # 가이드북 기준: Bearish 50% 이상 (공포) / Bullish 50% 이상 & 스프레드 극단 (과열)
    if bearish >= 50:
        return f"{msg} → Bearish 50%↑ 역발상 매수 점검"
    if bullish >= 50 and spread >= 20:
        return f"{msg} (스프레드 +{spread}%) → Bullish 50%↑ 과열 경계"
    return f"{msg} → 중립 범위"


# ------------------------------------------------------------------
# 4. 텔레그램 전송
# ------------------------------------------------------------------
def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("경고: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.")
        return

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
        print(f"CNN 수집 에러: {e}")
        fg_score, putcall_score = None, None

    try:
        vix = get_vix()
    except Exception as e:
        print(f"VIX 수집 에러: {e}")
        vix = None

    try:
        rsi = get_spy_rsi()
    except Exception as e:
        print(f"RSI 수집 에러: {e}")
        rsi = None

    bullish, neutral, bearish = get_aaii_sentiment()

    lines = [
        f"<b>미국주식 심리지표 알림</b> ({today})",
        "",
        f"1) CNN 공포탐욕지수: {judge_fear_greed(fg_score)}",
        f"2) Put/Call (CNN 하위지표): {judge_putcall(putcall_score)}",
        f"3) CBOE VIX: {judge_vix(vix)}",
        f"4) AAII 심리지수: {judge_aaii(bullish, neutral, bearish)}",
        f"5) S&P500(SPY) RSI: {judge_rsi(rsi)}",
    ]
    message = "\n".join(lines)

    print(message)  # GitHub Actions 실행 로그에서 확인 가능
    send_telegram(message)


if __name__ == "__main__":
    run()
