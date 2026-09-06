"""
한국 주식(삼성전자, SK하이닉스) 10분 간격 강제 알림 테스트 봇
- GitHub Actions 스케줄에 맞춰 실행 시 무조건 텔레그램 메시지 전송
"""

import os
import requests
import yfinance as yf
import datetime as dt
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
KST_TZ = ZoneInfo("Asia/Seoul")

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("텔레그램 토큰 또는 채널 ID가 없습니다.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=payload, timeout=10)

def analyze_kr_stock(ticker_symbol, name):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="6mo")
        if df.empty or len(df) < 20:
            return None

        current_price = int(df["Close"].iloc[-1])
        prev_close = df["Close"].iloc[-2]
        daily_change = round(((current_price - prev_close) / prev_close) * 100, 2)

        high_20d = int(df["High"].tail(20).max())
        drop_from_high = round(((current_price - high_20d) / high_20d) * 100, 1)

        # 1. 거래량 비율 (20일 평균 대비)
        vol_today = df["Volume"].iloc[-1]
        vol_20ma = df["Volume"].tail(20).mean()
        vol_ratio = round(vol_today / vol_20ma, 1) if vol_20ma > 0 else 0
        cond_vol = vol_ratio >= 1.5

        # 2. 볼린저밴드 하단 및 20일선
        sma20 = df["Close"].rolling(window=20).mean().iloc[-1]
        std20 = df["Close"].rolling(window=20).std().iloc[-1]
        bb_lower = int(sma20 - (2 * std20))
        cond_support = current_price <= bb_lower

        # 3. RSI(14)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1)
        cond_rsi = rsi <= 35

        # 4. 5일 이격도
        sma5 = df["Close"].rolling(window=5).mean().iloc[-1]
        disparity_5d = round((current_price / sma5) * 100, 1)
        cond_disparity = disparity_5d <= 95.0

        # 5. 당일 낙폭 (-3% 이상 하락 시 체크)
        cond_drop = daily_change <= -3.0

        checklist = [
            ("1. 당일 하락세", cond_drop, f"{daily_change}%"),
            ("2. 거래량 증가", cond_vol, f"평균 대비 {vol_ratio}배"),
            ("3. 볼린저하단 이탈", cond_support, f"하단가 {bb_lower:,}원"),
            ("4. 5일 이격도 공포", cond_disparity, f"{disparity_5d}%"),
            ("5. RSI 과매도", cond_rsi, f"RSI {rsi}")
        ]

        score = sum(1 for _, is_met, _ in checklist if is_met)

        # 분할 매수 타점 계산 (원화)
        p1 = current_price
        p2 = int(p1 * 0.97)
        p3 = int(p1 * 0.93)
        p4 = int(p1 * 0.88)

        buy_plan = (
            f"💼 <b>[{name} 500만 원 분할 매수 타점]</b>\n"
            f"├ <b>1차 (150만/30%)</b> : <code>{p1:,}원</code> (현재가 진입)\n"
            f"├ <b>2차 (150만/30%)</b> : <code>{p2:,}원</code> (-3% 추가하락)\n"
            f"├ <b>3차 (100만/20%)</b> : <code>{p3:,}원</code> (-7% 추가하락)\n"
            f"└ <b>4차 (100만/20%)</b> : <code>{p4:,}원</code> (-12% 패닉셀ing)"
        )

        return {
            "name": name,
            "code": ticker_symbol,
            "price": current_price,
            "daily_change": daily_change,
            "drop_from_high": drop_from_high,
            "score": score,
            "checklist": checklist,
            "buy_plan": buy_plan
        }
    except Exception as e:
        print(f"{name} 분석 실패: {e}")
        return None

def format_kr_section(data):
    if not data:
        return "⚠️ 데이터 수집 실패"

    name = data["name"]
    p = data["price"]
    chg = data["daily_change"]
    drop = data["drop_from_high"]
    score = data["score"]
    checklist = data["checklist"]
    plan = data["buy_plan"]

    chg_icon = "🔺" if chg > 0 else "🔻"
    chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"

    checklist_lines = []
    for title, is_met, detail in checklist:
        mark = "[✅]" if is_met else "[❌]"
        checklist_lines.append(f" {mark} <b>{title}</b> ({detail})")
    checklist_text = "\n".join(checklist_lines)

    stars = "🔥" * score + "⚪" * (5 - score)

    return (
        f"📊 <b>[{name} 현재 상태 테스트]</b> - {stars} ({score}/5개 충족)\n"
        f"• <b>현재가:</b> <code>{p:,}원</code> ({chg_icon} {chg_str})\n"
        f"• <b>20일 고점 대비:</b> {drop}%\n\n"
        f"📋 <b>[체크리스트 상태]</b>\n"
        f"{checklist_text}\n\n"
        f"{plan}"
    )

def run_test():
    now_kst = dt.datetime.now(KST_TZ).strftime("%Y-%m-%d %H:%M:%S KST")
    samsung = analyze_kr_stock("005930.KS", "삼성전자")
    hynix = analyze_kr_stock("000660.KS", "SK하이닉스")

    lines = [
        f"🧪 <b>[국장 10분 자동 테스트 알림]</b>",
        f"🕒 <i>{now_kst}</i>",
        "━━━━━━━━━━━━━━━━━━━━",
        format_kr_section(samsung),
        "------------------------------------",
        format_kr_section(hynix),
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>테스트용 강제 발송 모드 작동 중</i>"
    ]

    message = "\n".join(lines)
    send_telegram(message)
    print("텔레그램 테스트 메시지 전송 완료")

if __name__ == "__main__":
    run_test()
