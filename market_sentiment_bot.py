"""
미국주식 5대 심리지표 + SOXL / TQQQ / GDXU 5대 반등 조건 체크리스트 & 리포트
- CNN 공포탐욕지수 / Put-Call Ratio / CBOE VIX / AAII 심리지수 / S&P500 RSI
- 레버리지 3종(SOXL, TQQQ, GDXU) 10% 반등 5대 체크리스트 항시 수치화
- 체크리스트 3개 이상(또는 -7% 급락) 충족 시 매수 추천 및 500만원 분할매수 표 출력
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
# 3. 개별 레버리지 종목 5대 조건 정밀 분석 함수
# ------------------------------------------------------------------
def analyze_etf(ticker_symbol, vix_value):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1y")
        if df.empty or len(df) < 50:
            return None

        current_price = round(df["Close"].iloc[-1], 2)
        prev_close = df["Close"].iloc[-2]
        daily_change = round(((current_price - prev_close) / prev_close) * 100, 2)

        high_20d = df["High"].tail(20).max()
        drop_from_high = round(((current_price - high_20d) / high_20d) * 100, 1)

        # 1) 거래량 체크 (당일 거래량이 20일 평균의 1.5배 이상인가)
        vol_today = df["Volume"].iloc[-1]
        vol_20ma = df["Volume"].tail(20).mean()
        vol_ratio = round(vol_today / vol_20ma, 1) if vol_20ma > 0 else 0
        cond_volume = vol_ratio >= 1.5

        # 2) 지지선 중첩 체크 (볼린저 하단 이탈 OR 50일/200일선 3% 이내)
        sma20 = df["Close"].rolling(window=20).mean().iloc[-1]
        std20 = df["Close"].rolling(window=20).std().iloc[-1]
        bb_lower = round(sma20 - (2 * std20), 2)

        sma50 = df["Close"].rolling(window=50).mean().iloc[-1]
        sma200 = df["Close"].rolling(window=200).mean().iloc[-1] if len(df) >= 200 else None

        near_sma50 = abs(current_price - sma50) / sma50 <= 0.03
        near_sma200 = (abs(current_price - sma200) / sma200 <= 0.03) if sma200 else False
        is_bb_break = current_price <= bb_lower

        cond_support = is_bb_break or near_sma50 or near_sma200

        # 3) VIX & 5일 이격도 체크 (VIX >= 25 OR 5일 이격도 <= 92%)
        sma5 = df["Close"].rolling(window=5).mean().iloc[-1]
        disparity_5d = round((current_price / sma5) * 100, 1)
        cond_vix_disparity = (vix_value is not None and vix_value >= 25) or (disparity_5d <= 92.0)

        # 4) 아래꼬리 반등 / RSI 체크 (RSI <= 35 OR 저점대비 +1.5% 이상 반등)
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

        # 체크리스트 평가 (5개 항목)
        checklist = [
            ("1. 전일대비 급락", cond_daily_plunge, f"{daily_change}% 하락"),
            ("2. 거래량 폭발", cond_volume, f"평소 대비 {vol_ratio}배"),
            ("3. 지지선 중첩", cond_support, f"볼린저하단 ${bb_lower}" if is_bb_break else "주요 이평선 근접"),
            ("4. 이격도/VIX 공포", cond_vix_disparity, f"5일 이격 {disparity_5d}% / VIX {vix_value}"),
            ("5. 반등/RSI 과매도", cond_rebound, f"RSI {rsi} / 저점대비 +{rebound_from_low}%")
        ]

        score = sum(1 for _, is_met, _ in checklist if is_met)

        # 500만원 분할 매수 타점 계산
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
            "buy_plan": buy_plan
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

    chg_icon = "🔺" if chg > 0 else "🔻"
    chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"
    drop_emoji = "🟢" if drop <= -20.0 else "⚪"

    # 체크리스트 텍스트 구성
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

    # 매수 추천도 평가 (3개 이상 충족 시 매수 추천)
    stars = "🔥" * score + "⚪" * (5 - score)

    if score >= 3 or chg <= -7.0:
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
# 4. 시장 지표 판정 문구 함수들
# ------------------------------------------------------------------
def judge_fear_greed(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🟢 <b>{score}</b> (극단적 공포 - 매수 점검)"
    if score >= 75: return f"🔴 <b>{score}</b> (극단적 탐욕 - 과열 경계)"
    return f"⚪ <b>{score}</b> (중립~보통)"

def judge_putcall(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🔴 <b>{score}</b> (콜 쏠림 - 과도한 낙관)"
    if score >= 75: return f"🟢 <b>{score}</b> (풋 쏠림 - 공포 진입)"
    return f"⚪ <b>{score}</b> (중립 범위)"

def judge_vix(vix):
    if vix is None: return "⚪ 데이터 없음"
    if vix >= 40: return f"🟢 <b>{vix}</b> (40 이상 - 패닉·급등 구간)"
    if vix <= 13: return f"🔴 <b>{vix}</b> (13 이하 - 안일함/과열 점검)"
    return f"⚪ <b>{vix}</b> (평온~경계 범위)"

def judge_rsi(rsi):
    if rsi is None: return "⚪ 데이터 없음"
    if rsi <= 30: return f"🟢 <b>{rsi}</b> (30 이하 - 과매도/공포)"
    if rsi >= 70: return f"🔴 <b>{rsi}</b> (70 이상 - 과매수/과열)"
    return f"⚪ <b>{rsi}</b> (중립 범위)"

def judge_aaii(bullish, neutral, bearish):
    if bearish is None or bullish is None: return "⚪ 데이터 없음"
    spread = round(bullish - bearish, 1)
    msg = f"Bull {bullish}% / Bear {bearish}%"
    if bearish >= 50: return f"🟢 <b>{msg}</b> (Bearish 50%↑ 역발상 매수)"
    if bullish >= 50 and spread >= 20: return f"🔴 <b>{msg}</b> (Bullish 50%↑ 과열)"
    return f"⚪ <b>{msg}</b> (중립)"

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

    if fear_count >= 2:
        return f"💡 <b>종합 의견:</b> 🟢 <b>역발상 매수 점검</b> (공포 신호 {fear_count}개 감지)"
    elif greed_count >= 2:
        return f"💡 <b>종합 의견:</b> 🔴 <b>과열 경계 / 현금 확보</b> (과열 신호 {greed_count}개 감지)"
    return "💡 <b>종합 의견:</b> ⚪ <b>중립 / 관망 유효</b>"

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

    fg_score, putcall_score = get_cnn_fear_greed()
    vix = get_vix()
    rsi = get_spy_rsi()
    bullish, neutral, bearish = get_aaii_sentiment()

    soxl_data = analyze_etf("SOXL", vix)
    tqqq_data = analyze_etf("TQQQ", vix)
    gdxu_data = analyze_etf("GDXU", vix)

    lines = [
        f"📈 <b>미국주식 심리지표 & 레버리지 리포트</b>",
        f"🕒 <i>{today} 기준</i>",
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
        format_etf_section(gdxu_data),
        "━━━━━━━━━━━━━━━━━━━━",
        get_overall_opinion(fg_score, putcall_score, vix, rsi, bullish, bearish)
    ]

    message = "\n".join(lines)
    send_telegram(message)

if __name__ == "__main__":
    run()
