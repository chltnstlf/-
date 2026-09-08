"""
미국증시 3대 정기 브리핑 + 긴급 알림 + 수동 조회 통합 봇
- 정기 브리핑: 08:00 KST (마감), 21:00 KST (프리마켓), 23:00 KST (본장)
- 긴급 알림: 6대 심리지표 중 3개 이상 '극단적 공포' 조건 충족 시에만 전송
- 수동 조회: 버튼 클릭/수동 실행 시 조건 상관없이 즉시 실시간 리포트 전송
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
# 2. 시간 및 장 상태 판정
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

    if weekday >= 5:
        status_text = "미국 주말 휴장"
    else:
        if 400 <= ny_time_num < 930:
            status_text = "미국 프리마켓 진행 중"
        elif 930 <= ny_time_num < 1600:
            status_text = "미국 정규장(본장) 진행 중"
        elif 1600 <= ny_time_num < 2000:
            status_text = "미국 애프터마켓 진행 중"
        else:
            status_text = "미국 장외/휴장 시간"

    header_time_str = f"🕒 {kst_str}\n[{status_text} | 현지 {ny_time_str} {tz_name}]"
    return {
        "kst_hour": now_kst.hour,
        "kst_minute": now_kst.minute,
        "header_time_str": header_time_str,
        "weekday": weekday
    }

# ------------------------------------------------------------------
# 3. 데이터 수집 함수들
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
        print(f"CNN 수집 실패: {e}")
        return None, None

def get_vix():
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        return round(hist["Close"].iloc[-1], 2)
    except Exception as e:
        print(f"VIX 수집 실패: {e}")
        return None

def get_vxn():
    try:
        vxn = yf.Ticker("^VXN")
        hist = vxn.history(period="5d")
        return round(hist["Close"].iloc[-1], 2)
    except Exception as e:
        print(f"VXN 수집 실패: {e}")
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
        return float(data.get("bullish", 0)), float(data.get("neutral", 0)), float(data.get("bearish", 0))
    except Exception as e:
        print(f"AAII 읽기 실패: {e}")
        return None, None, None

def get_market_data(ticker_symbol, is_yield=False):
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d")
        if hist.empty or len(hist) < 2: return None, None
        curr = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        if is_yield:
            c = round(curr / 10 if curr > 20 else curr, 2)
            p = round(prev / 10 if prev > 20 else prev, 2)
            return c, round(c - p, 2)
        else:
            c = round(curr, 2)
            return c, round(((c - prev) / prev) * 100, 2)
    except Exception as e:
        print(f"{ticker_symbol} 실패: {e}")
        return None, None

# ------------------------------------------------------------------
# 4. 판정 및 긴급 조건 감지 로직
# ------------------------------------------------------------------
def judge_fear_greed(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🟢 <b>{score}</b> (극단적 공포)"
    if score >= 75: return f"🔴 <b>{score}</b> (극단적 탐욕)"
    return f"⚪ <b>{score}</b> (중립~보통)"

def judge_putcall(score):
    if score is None: return "⚪ 데이터 없음"
    if score <= 25: return f"🟢 <b>{score}</b> (풋옵션 쏠림/공포)"
    if score >= 75: return f"🔴 <b>{score}</b> (콜옵션 쏠림/과열)"
    return f"⚪ <b>{score}</b> (중립)"

def judge_vix(vix):
    if vix is None: return "⚪ 데이터 없음"
    if vix >= 25: return f"🟢 <b>{vix}</b> (시장 공포/급등)"
    if vix <= 13: return f"🔴 <b>{vix}</b> (과열 점검)"
    return f"⚪ <b>{vix}</b> (평온~경계)"

def judge_vxn(vxn):
    if vxn is None: return "⚪ 데이터 없음"
    if vxn >= 30: return f"🟢 <b>{vxn}</b> (기술주 패닉)"
    if vxn <= 16: return f"🔴 <b>{vxn}</b> (과열 점검)"
    return f"⚪ <b>{vxn}</b> (평온~경계)"

def judge_rsi(rsi):
    if rsi is None: return "⚪ 데이터 없음"
    if rsi <= 35: return f"🟢 <b>{rsi}</b> (과매도 구간)"
    if rsi >= 70: return f"🔴 <b>{rsi}</b> (과매수 구간)"
    return f"⚪ <b>{rsi}</b> (중립)"

def judge_aaii(bullish, neutral, bearish):
    if bearish is None or bullish is None: return "⚪ 데이터 없음"
    msg = f"Bull {bullish}% / Bear {bearish}%"
    if bearish >= 45: return f"🟢 <b>{msg}</b> (비관론 45%↑ 역발상 매수)"
    if bullish >= 50: return f"🔴 <b>{msg}</b> (과열)"
    return f"⚪ <b>{msg}</b> (중립)"

def check_extreme_fear_alerts(fg, pc, vix, vxn, rsi, bearish):
    """6개 심리지표 중 3개 이상 '극단적 공포' 조건 충족 여부 확인"""
    fear_triggers = []

    if fg is not None and fg <= 25:
        fear_triggers.append(f"• CNN 공포탐욕지수 극단적 공포 ({fg}pt)")
    if pc is not None and pc <= 25:
        fear_triggers.append(f"• Put/Call Ratio 풋옵션 쏠림 ({pc}pt)")
    if vix is not None and vix >= 25.0:
        fear_triggers.append(f"• CBOE VIX 급등 ({vix})")
    if vxn is not None and vxn >= 30.0:
        fear_triggers.append(f"• CBOE VXN 기술주 패닉 ({vxn})")
    if rsi is not None and rsi <= 35.0:
        fear_triggers.append(f"• SPY RSI 과매도 ({rsi})")
    if bearish is not None and bearish >= 45.0:
        fear_triggers.append(f"• AAII 개인 비관론 폭증 ({bearish}%)")

    return len(fear_triggers) >= 3, fear_triggers

def format_val(val, chg, unit="", is_bp=False, is_int=False):
    if val is None: return "⚪ 데이터 없음"
    icon = "🔺" if chg > 0 else "🔻" if chg < 0 else "➖"
    chg_str = f"+{chg}" if chg > 0 else f"{chg}"
    suffix = "%p" if is_bp else "%"
    formatted_val = f"{int(val):,}" if is_int else f"{val:,.2f}"
    return f"<code>{formatted_val}{unit}</code> ({icon} {chg_str}{suffix})"

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(",") if cid.strip()]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in chat_ids:
        try:
            requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            print(f"텔레그램 전송 실패 ({chat_id}): {e}")

# ------------------------------------------------------------------
# 5. 리포트 생성 및 구분 발송 함수
# ------------------------------------------------------------------
def generate_and_send_report(mode="MANUAL", briefing_title=None):
    """
    mode 옵션:
    - "BRIEFING": 정기 브리핑 (무조건 발송)
    - "EMERGENCY": 긴급 알림 모니터링 (3개 이상 공포 시에만 발송)
    - "MANUAL": 수동 요청/테스트 실행 (무조건 발송)
    """
    status_info = get_market_status_info()
    
    # 지표 수집
    fg_score, putcall_score = get_cnn_fear_greed()
    vix = get_vix()
    vxn = get_vxn()
    rsi = get_spy_rsi()
    bullish, neutral, bearish = get_aaii_sentiment()

    # 긴급 알림 조건 검증
    is_triggered, triggers = check_extreme_fear_alerts(fg_score, putcall_score, vix, vxn, rsi, bearish)

    # 모니터링 모드인데 긴급 알림 조건 미충족 시 전송 안 함
    if mode == "EMERGENCY" and not is_triggered:
        print("긴급 알림 조건 미충족 (극단 공포 3개 미만) -> 전송 스킵")
        return

    # 증시 및 거시경제 수집
    dow_p, dow_c       = get_market_data("^DJI")
    sp500_p, sp500_c   = get_market_data("^GSPC")
    nasdaq_p, nasdaq_c = get_market_data("^IXIC")
    kospi_p, kospi_c   = get_market_data("^KS11")

    wti_p, wti_c     = get_market_data("CL=F")
    gold_p, gold_c   = get_market_data("GC=F")
    slv_p, slv_c     = get_market_data("SI=F")
    krw_p, krw_c     = get_market_data("KRW=X")
    jpy_p, jpy_c     = get_market_data("JPY=X")
    tnx_p, tnx_c     = get_market_data("^TNX", is_yield=True)
    btc_p, btc_c     = get_market_data("BTC-USD")

    # [구분 1] 헤더 타이틀 명확히 분기
    if mode == "EMERGENCY":
        title_header = f"🚨 <b>[긴급 알림 | 매수 타점 경보 (공포 지표 {len(triggers)}개 감지)]</b>\n"
    elif mode == "BRIEFING":
        title_header = f"📢 <b>[정기 브리핑 | {briefing_title}]</b>\n"
    else: # MANUAL
        title_header = "🔍 <b>[수동 요청 | 실시간 증시 점검 리포트]</b>\n"

    lines = [
        title_header,
        status_info["header_time_str"]
    ]

    # 긴급 공포 조건 감지 시 사유 표시 (수동 요청 시에도 감지되었으면 알려줌)
    if is_triggered:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🔥 <b>[긴급 공포 감지 사유]</b>")
        lines.extend(triggers)

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 <b>[미국주식 6대 심리지표]</b>",
        f"1. <b>CNN 공포탐욕지수:</b> {judge_fear_greed(fg_score)}",
        f"2. <b>Put/Call Ratio:</b> {judge_putcall(putcall_score)}",
        f"3. <b>CBOE VIX (S&P500):</b> {judge_vix(vix)}",
        f"4. <b>CBOE VXN (나스닥):</b> {judge_vxn(vxn)}",
        f"5. <b>AAII 심리지수:</b> {judge_aaii(bullish, neutral, bearish)}",
        f"6. <b>S&P500 RSI:</b> {judge_rsi(rsi)}",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>[주요 증시 지수]</b>",
        f"🇺🇸 <b>다우 존스:</b> {format_val(dow_p, dow_c, 'pt')}",
        f"🇺🇸 <b>S&P 500:</b> {format_val(sp500_p, sp500_c, 'pt')}",
        f"🇺🇸 <b>나스닥 종합:</b> {format_val(nasdaq_p, nasdaq_c, 'pt')}",
        f"🇰🇷 <b>코스피 지수:</b> {format_val(kospi_p, kospi_c, 'pt')}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🌐 <b>[핵심 거시경제 지표]</b>",
        f"🛢️ <b>WTI 유가:</b> {format_val(wti_p, wti_c, '$')}",
        f"🪙 <b>금 (Gold):</b> {format_val(gold_p, gold_c, '$')}",
        f"🥈 <b>은 (Silver):</b> {format_val(slv_p, slv_c, '$')}",
        f"💵 <b>달러/원 (USD/KRW):</b> {format_val(krw_p, krw_c, '원')}",
        f"💴 <b>달러/엔 (USD/JPY):</b> {format_val(jpy_p, jpy_c, '엔')}",
        f"🏛️ <b>미 10년물 국채금리:</b> {format_val(tnx_p, tnx_c, '%', is_bp=True)}",
        f"₿ <b>비트코인 (BTC):</b> {format_val(btc_p, btc_c, '$', is_int=True)}",
        "━━━━━━━━━━━━━━━━━━━━"
    ])

    send_telegram("\n".join(lines))
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] [{mode}] 리포트 전송 완료!")

# ------------------------------------------------------------------
# 6. 실행부 (GitHub Actions & 수동 실행 완벽 분기)
# ------------------------------------------------------------------
def run_once():
    """GitHub Actions 및 단발성 실행 전용"""
    status = get_market_status_info()
    h, m = status["kst_hour"], status["kst_minute"]

    # 수동 실행 변수 체크 (깃허브 수동버튼 누름 or 컴퓨터 환경변수로 지정)
    is_manual = (
        os.environ.get("MANUAL_RUN") == "true" or 
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    )

    if is_manual:
        # 수동 트리거일 경우 시간 무관하게 즉시 발송
        generate_and_send_report(mode="MANUAL")
    elif h == 8 and m < 20:
        generate_and_send_report(mode="BRIEFING", briefing_title="☀️ 아침 미국장 마감 & 국내장 대비")
    elif h == 21 and m < 20:
        generate_and_send_report(mode="BRIEFING", briefing_title="🌙 저녁 프리마켓 & 지표발표 점검")
    elif h == 23 and m < 20:
        generate_and_send_report(mode="BRIEFING", briefing_title="🌃 밤 미국 본장 개장 수급 점검")
    else:
        # 자동 크론 정기 체크 시에는 긴급 조건일 때만 발송
        generate_and_send_report(mode="EMERGENCY")

def main_loop():
    """내 PC에서 24시간 돌릴 때"""
    print("🚀 봇이 시작되었습니다. (시작 즉시 점검 리포트 전송)")
    generate_and_send_report(mode="MANUAL")

    last_briefing_hour = -1

    while True:
        status = get_market_status_info()
        h = status["kst_hour"]

        if h in [8, 21, 23] and h != last_briefing_hour:
            titles = {
                8: "☀️ 아침 미국장 마감 & 국내장 대비",
                21: "🌙 저녁 프리마켓 & 지표발표 점검",
                23: "🌃 밤 미국 본장 개장 수급 점검"
            }
            generate_and_send_report(mode="BRIEFING", briefing_title=titles[h])
            last_briefing_hour = h
        else:
            generate_and_send_report(mode="EMERGENCY")

        time.sleep(900)

if __name__ == "__main__":
    if os.environ.get("RUN_ONCE") == "true":
        run_once()
    else:
        main_loop()
