"""
미국주식 5대 심리지표 + SOXL 과대낙폭 & 4차 분할매수 텔레그램 알림 봇
- CNN 공포탐욕지수 / Put-Call Ratio / CBOE VIX / AAII 심리지수 / S&P500 RSI
- SOXL 과대낙폭(RSI, MDD, 볼린저밴드) 및 500만원(150/150/100/100) 분할매수 가이드
- 장중 급락 시 긴급 알림 전송 기능 지원
"""

import os
import json
import requests
import yfinance as yf
import datetime as dt

# ------------------------------------------------------------------
# 1. 설정값
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ------------------------------------------------------------------
# 2. 시장 심리지표 수집 함수
# ------------------------------------------------------------------
def get_cnn_fear_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    fg_score = data["fear_and_greed"]["score"]
    putcall_score = data["put_call_options"]["score"]
    return round(fg_score, 1), round(putcall_score, 1)

def get_vix():
    vix = yf.Ticker("^VIX")
    hist = vix.history(period="5d")
    return round(hist["Close"].iloc[-1], 2)

def get_spy_rsi(period=14):
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
# 3. SOXL 과대낙폭 및 4단계 분할 매수 수집 함수
# ------------------------------------------------------------------
def get_soxl_metrics():
    try:
        soxl = yf.Ticker("SOXL")
        df = soxl.history(period="6mo")
        if df.empty or len(df) < 30:
            return None

        # 현재가 및 일간 변동률
        current_price = round(df["Close"].iloc[-1], 2)
        prev_close = df["Close"].iloc[-2]
        daily_change = round(((current_price - prev_close) / prev_close) * 100, 2)

        # 20일 고점 대비 낙폭 (MDD)
        high_20d = df["High"].tail(20).max()
        drop_from_high = round(((current_price - high_20d) / high_20d) * 100, 1)

        # RSI(14)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1)

        # 볼린저 밴드 하단 (20일 SMA, 2표준편차)
        sma20 = df["Close"].rolling(window=20).mean().iloc[-1]
        std20 = df["Close"].rolling(window=20).std().iloc[-1]
        bb_lower = round(sma20 - (2 * std20), 2)
        is_bb_break = current_price <= bb_lower

        # 과대낙폭 신호 수집
        signals = []
        if drop_from_high <= -20.0:
            signals.append(f"고점대비 낙폭 심화({drop_from_high}%)")
        if rsi <= 35:
            signals.append(f"RSI 과매도({rsi})")
        if is_bb_break:
            signals.append(f"볼린저밴드 하단 이탈(${bb_lower})")

        # 4단계 분할 매수 가격 타점 계산 (500만원 예산 기준)
        p1 = current_price
        p2 = round(p1 * 0.93, 2)  # -7%
        p3 = round(p1 * 0.85, 2)  # -15%
        p4 = round(p1 * 0.75, 2)  # -25%

        buy_plan = (
            f"💰 <b>[500만원 분할 매수 목표 가이드]</b>\n"
            f"• 1차(150만원 / 30%): <b>${p1}</b> (현재가 진입)\n"
            f"• 2차(150만원 / 30%): <b>${p2}</b> (-7% 추가하락 시)\n"
            f"• 3차(100만원 / 20%): <b>${p3}</b> (-15% 추가하락 시)\n"
            f"• 4차(100만원 / 20%): <b>${p4}</b> (-25% 추가하락 패닉시)"
        )

        return {
            "price": current_price,
            "daily_change": daily_change,
            "drop_from_high": drop_from_high,
            "rsi": rsi,
            "bb_lower": bb_lower,
            "signals": signals,
            "signal_count": len(signals),
            "buy_plan": buy_plan
        }
    except Exception as e:
        print(f"SOXL 데이터 분석 실패: {e}")
        return None

# ------------------------------------------------------------------
# 4. 판정 문구 함수들
# ------------------------------------------------------------------
def judge_fear_greed(score):
    if score is None: return "데이터 없음"
    if score <= 25: return f"{score} → 극단적 공포 (매수 점검 구간)"
    if score >= 75: return f"{score} → 극단적 탐욕 (과열 경계 구간)"
    return f"{score} → 중립~보통 범위"

def judge_putcall(score):
    if score is None: return "데이터 없음"
    if score <= 25: return f"{score} → 콜 쏠림(과도한 낙관) 근접"
    if score >= 75: return f"{score} → 풋 쏠림(공포) 근접"
    return f"{score} → 중립 범위"

def judge_vix(vix):
    if vix is None: return "데이터 없음"
    if vix >= 40: return f"{vix} → 40 이상, 패닉·급등 구간"
    if vix <= 13: return f"{vix} → 12~13대, 장기 저공비행(안일함 점검)"
    return f"{vix} → 평온~경계 범위"

def judge_rsi(rsi):
    if rsi is None: return "데이터 없음"
    if rsi <= 30: return f"{rsi} → 30 근접/이하, 과매도(공포)"
    if rsi >= 70: return f"{rsi} → 70 이상, 과매수(과열)"
    return f"{rsi} → 중립 범위"

def judge_aaii(bullish, neutral, bearish):
    if bearish is None or bullish is None: return "데이터 없음"
    spread = round(bullish - bearish, 1)
    msg = f"Bull {bullish}% / Neutral {neutral}% / Bear {bearish}%"
    if bearish >= 50: return f"{msg} → Bearish 50%↑ 역발상 매수 점검"
    if bullish >= 50 and spread >= 20: return f"{msg} (스프레드 +{spread}%) → Bullish 50%↑ 과열 경계"
    return f"{msg} → 중립 범위"

def get_overall_opinion(fg, putcall, vix, rsi, aaii_bull, aaii_bear):
    fear_count = 0
    greed_count = 0
    if fg is not None:
        if fg <= 25: fear_count += 1
        elif fg >= 75: greed_count += 1
    if putcall is not None:
        if putcall >= 75: fear_count += 1
        elif putcall <= 25: greed_count += 1
    if vix is not None:
        if vix >= 40: fear_count += 1
        elif vix <= 13: greed_count += 1
    if rsi is not None:
        if rsi <= 30: fear_count += 1
        elif rsi >= 70: greed_count += 1
    if aaii_bear is not None and aaii_bull is not None:
        if aaii_bear >= 50: fear_count += 1
        elif aaii_bull >= 50 and (aaii_bull - aaii_bear) >= 20: greed_count += 1

    if fear_count >= 2: return f"🟢 <b>[종합 의견: 역발상 매수 점검]</b> (공포 신호 {fear_count}개 감지 - 분할 매수 고려)"
    elif greed_count >= 2: return f"🔴 <b>[종합 의견: 과열 경계 / 현금 확보]</b> (과열 신호 {greed_count}개 감지 - 비중 축소 고려)"
    return "⚪ <b>[종합 의견: 중립 / 관망 범위]</b>"

# ------------------------------------------------------------------
# 5. 텔레그램 전송
# ------------------------------------------------------------------
def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=payload, timeout=10)

# ------------------------------------------------------------------
# 6. 메인 실행
# ------------------------------------------------------------------
def run():
    today = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 지표 수집
    fg_score, putcall_score = get_cnn_fear_greed()
    vix = get_vix()
    rsi = get_spy_rsi()
    bullish, neutral, bearish = get_aaii_sentiment()
    soxl_data = get_soxl_metrics()

    # SOXL 메시지 구성
    soxl_msg = "SOXL 데이터 수집 실패"
    if soxl_data:
        p = soxl_data["price"]
        chg = soxl_data["daily_change"]
        drop = soxl_data["drop_from_high"]
        r = soxl_data["rsi"]
        cnt = soxl_data["signal_count"]
        plan = soxl_data["buy_plan"]

        # 긴급 급락 신호 또는 과대낙폭 매수 타점 발생 조건
        if chg <= -7.0 or cnt >= 2:
            soxl_msg = (
                f"🚨 <b>[SOXL 긴급 과대낙폭 / 급락 알림]</b>\n"
                f"• 현재가: <b>${p}</b> (전일대비 {chg}%)\n"
                f"• 20일 고점대비: <b>{drop}%</b> / RSI: <b>{r}</b>\n"
                f"• 충족 신호({cnt}개): {', '.join(soxl_data['signals'])}\n\n"
                f"{plan}"
            )
        elif cnt == 1:
            soxl_msg = (
                f"⚠️ <b>[SOXL 낙폭 관찰 구간]</b> (${p} / 전일대비 {chg}%)\n"
                f"• 감지된 신호: {soxl_data['signals'][0]}"
            )
        else:
            soxl_msg = f"⚪ <b>[SOXL 정상 범위]</b> (${p} / 전일대비 {chg}%)"

    lines = [
        f"<b>미국주식 심리지표 & SOXL 분할매수 알림</b> ({today})",
        "",
        f"1) CNN 공포탐욕지수: {judge_fear_greed(fg_score)}",
        f"2) Put/Call (CNN 하위지표): {judge_putcall(putcall_score)}",
        f"3) CBOE VIX: {judge_vix(vix)}",
        f"4) AAII 심리지수: {judge_aaii(bullish, neutral, bearish)}",
        f"5) S&P500(SPY) RSI: {judge_rsi(rsi)}",
        "",
        "----------------------------------------",
        soxl_msg,
        "----------------------------------------",
        "",
        get_overall_opinion(fg_score, putcall_score, vix, rsi, bullish, bearish)
    ]

    message = "\n".join(lines)
    send_telegram(message)

if __name__ == "__main__":
    run()
