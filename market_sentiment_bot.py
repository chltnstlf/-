"""
미국주식 5대 심리지표 + SOXL / TQQQ / GDXU 과대낙폭 & 4차 분할매수 리포트
- CNN 공포탐욕지수 / Put-Call Ratio / CBOE VIX / AAII 심리지수 / S&P500 RSI
- 레버리지 3종(SOXL, TQQQ, GDXU) 전 지표 항시 모니터링
- '전일 대비 -7% 이상 급락'을 핵심 매수 스위치로 설정
- 과대낙폭 조건 충족 시에만 500만원(150/150/100/100) 분할매수 타점표 출력
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
# 3. 개별 레버리지 종목 분석 함수 (SOXL / TQQQ / GDXU)
# ------------------------------------------------------------------
def analyze_etf(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="6mo")
        if df.empty or len(df) < 30:
            return None

        current_price = round(df["Close"].iloc[-1], 2)
        prev_close = df["Close"].iloc[-2]
        daily_change = round(((current_price - prev_close) / prev_close) * 100, 2)

        high_20d = df["High"].tail(20).max()
        drop_from_high = round(((current_price - high_20d) / high_20d) * 100, 1)

        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1)

        sma20 = df["Close"].rolling(window=20).mean().iloc[-1]
        std20 = df["Close"].rolling(window=20).std().iloc[-1]
        bb_lower = round(sma20 - (2 * std20), 2)
        is_bb_break = current_price <= bb_lower

        # 핵심 매수 신호 판정: 전일 대비 -7% 이상 급락 여부
        is_daily_plunge = daily_change <= -7.0

        signals = []
        if is_daily_plunge:
            signals.append(f"전일대비 급락({daily_change}%)")
        if drop_from_high <= -20.0:
            signals.append(f"20일 고점대비({drop_from_high}%)")
        if rsi <= 35:
            signals.append(f"RSI 과매도({rsi})")
        if is_bb_break:
            signals.append(f"볼린저 하단이탈(${bb_lower})")

        # 500만원 분할 매수 타점 계산 (1차=현재가 / 2차=-7% / 3차=-15% / 4차=-25%)
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
            "bb_lower": bb_lower,
            "is_bb_break": is_bb_break,
            "is_daily_plunge": is_daily_plunge,
            "signals": signals,
            "signal_count": len(signals),
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
    r = data["rsi"]
    bb = data["bb_lower"]
    is_bb = data["is_bb_break"]
    is_plunge = data["is_daily_plunge"]
    cnt = data["signal_count"]
    signals = data["signals"]
    plan = data["buy_plan"]

    chg_icon = "🔺" if chg > 0 else "🔻"
    chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"

    # 이모지 상태 판정 (전일대비 급락 또는 과매도는 🟢)
    chg_emoji = "🟢" if is_plunge else "⚪"
    rsi_emoji = "🟢" if r <= 35 else ("🔴" if r >= 70 else "⚪")
    drop_emoji = "🟢" if drop <= -20.0 else "⚪"
    bb_emoji = "🟢" if is_bb else "⚪"

    bb_status = "하단 이탈" if is_bb else "상회"

    metrics_text = (
        f"• <b>현재가:</b> <code>${p}</code> ({chg_icon} {chg_str})\n"
        f"• <b>20일 고점 대비:</b> {drop_emoji} {drop}%\n"
        f"• <b>RSI(14):</b> {rsi_emoji} {r}\n"
        f"• <b>볼린저 하단:</b> {bb_emoji} ${bb} ({bb_status})"
    )

    # 매수 타점표 발동 조건: 전일 대비 -7% 이상 급락했거나, 과매도 신호 2개 이상 발생 시
    if is_plunge or cnt >= 2:
        return (
            f"🚨 <b>[{sym} 긴급 과대낙폭 / 매수 타점]</b>\n"
            f"{metrics_text}\n"
            f"• <b>포착 신호({cnt}개):</b> {', '.join(signals)}\n\n"
            f"{plan}"
        )
    elif cnt == 1:
        return (
            f"⚠️ <b>[{sym} 낙폭 관찰 구간]</b> (포착 신호: {signals[0]})\n"
            f"{metrics_text}"
        )
    else:
        return (
            f"📊 <b>[{sym} 정상 범위]</b>\n"
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

    soxl_data = analyze_etf("SOXL")
    tqqq_data = analyze_etf("TQQQ")
    gdxu_data = analyze_etf("GDXU")

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
