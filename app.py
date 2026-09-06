"""E-commerce Operations Analysis Agent - dependency-free portfolio MVP."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "daily_operations.csv"


def make_demo_data() -> None:
    """Create reproducible daily aggregate data with realistic business signals."""
    DATA.parent.mkdir(exist_ok=True)
    rng = random.Random(42)
    start = date.today() - timedelta(days=89)
    campaigns = [("SAVE50", "50 元折扣", 0.31), ("FREE100", "滿 999 折 100", 0.18), ("NONE", "未使用優惠券", 0.51)]
    rows = []
    for day in range(90):
        current = start + timedelta(days=day)
        weekly = 1.12 if current.weekday() in (4, 5) else 1.0
        trend = 1 + day * 0.0015
        # Recent period: demand rises while SAVE50 weakens, creating explainable alerts.
        demand_shock = 1.13 if day >= 83 else 1
        for code, campaign, share in campaigns:
            if day >= 86 and code == "SAVE50":
                share *= 0.62
            orders = max(20, round((610 * share * weekly * trend * demand_shock) + rng.gauss(0, 20)))
            aov = {"SAVE50": 720, "FREE100": 1060, "NONE": 820}[code] + rng.gauss(0, 32)
            discount = {"SAVE50": 50, "FREE100": 100, "NONE": 0}[code]
            revenue = round(orders * aov)
            rows.append({
                "date": current.isoformat(), "coupon_code": code, "campaign": campaign,
                "orders": orders, "revenue": revenue, "discount_cost": orders * discount,
                "daily_capacity": 720 if day < 83 else 690,
            })
    with DATA.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)


def read_rows() -> list[dict]:
    if not DATA.exists(): make_demo_data()
    with DATA.open(encoding="utf-8") as f:
        return [{**r, "orders": int(r["orders"]), "revenue": int(r["revenue"]),
                 "discount_cost": int(r["discount_cost"]), "daily_capacity": int(r["daily_capacity"])}
                for r in csv.DictReader(f)]


def percent(value: float) -> str: return f"{value * 100:+.1f}%"


def calculate() -> dict:
    rows = read_rows()
    dates = sorted({r["date"] for r in rows})
    daily = []
    for d in dates:
        group = [r for r in rows if r["date"] == d]
        orders = sum(r["orders"] for r in group); revenue = sum(r["revenue"] for r in group)
        daily.append({"date": d, "orders": orders, "revenue": revenue,
                      "aov": round(revenue / orders), "discount_cost": sum(r["discount_cost"] for r in group),
                      "capacity": group[0]["daily_capacity"], "utilization": round(orders / group[0]["daily_capacity"], 3)})
    today, yesterday = daily[-1], daily[-2]
    forecast = round(sum(d["orders"] for d in daily[-7:]) / 7)
    capacity_gap = forecast - today["capacity"]
    coupons = []
    total_orders = today["orders"]
    for code in ("SAVE50", "FREE100", "NONE"):
        now = next(r for r in rows if r["date"] == today["date"] and r["coupon_code"] == code)
        prev = next(r for r in rows if r["date"] == yesterday["date"] and r["coupon_code"] == code)
        roi = None if not now["discount_cost"] else round((now["revenue"] - now["discount_cost"]) / now["discount_cost"], 2)
        coupons.append({"code": code, "campaign": now["campaign"], "orders": now["orders"],
                        "usage_rate": round(now["orders"] / total_orders, 3), "revenue": now["revenue"],
                        "discount_cost": now["discount_cost"], "aov": round(now["revenue"] / now["orders"]),
                        "roi": roi, "order_change": round((now["orders"] - prev["orders"]) / prev["orders"], 3)})
    revenue_change = (today["revenue"] - yesterday["revenue"]) / yesterday["revenue"]
    insights = []
    if today["utilization"] >= .9:
        insights.append({"level": "warning", "title": "產能接近上限", "detail": f"今日產能利用率 {today['utilization']:.0%}；預測明日訂單 {forecast:,}，較目前產能多 {max(0, capacity_gap):,} 筆。"})
    save = next(c for c in coupons if c["code"] == "SAVE50")
    if save["order_change"] < -.15:
        insights.append({"level": "watch", "title": "SAVE50 使用量下降", "detail": f"較前一日 {percent(save['order_change'])}。建議檢查曝光位置、適用商品與門檻設定。"})
    insights.append({"level": "info", "title": "促銷客單價洞察", "detail": "FREE100 的 AOV 較 SAVE50 高，可作為高客單商品的分眾優惠候選。"})
    return {"today": today, "yesterday": yesterday, "forecast": forecast, "capacity_gap": capacity_gap,
            "revenue_change": revenue_change, "daily": daily[-14:], "coupons": coupons, "insights": insights}


def answer(question: str, d: dict) -> str:
    """A transparent, source-grounded Q&A layer; never invents values."""
    q = question.lower()
    t = d["today"]
    if any(k in q for k in ("營收", "revenue", "業績", "下降")):
        direction = "增加" if d["revenue_change"] >= 0 else "下降"
        return f"{t['date']} 營收為 NT${t['revenue']:,}，較前一日{direction} {abs(d['revenue_change']):.1%}。請搭配訂單量、AOV 與優惠券使用率檢視原因；本資料中 SAVE50 訂單較昨日 {percent(next(c for c in d['coupons'] if c['code']=='SAVE50')['order_change'])}。"
    if any(k in q for k in ("產能", "forecast", "預測", "capacity")):
        gap = d["capacity_gap"]
        status = f"超出目前產能 {gap:,} 筆" if gap > 0 else f"仍有 {-gap:,} 筆餘裕"
        return f"以最近 7 天訂單平均預測，明日需求約 {d['forecast']:,} 筆；目前日產能 {t['capacity']:,} 筆，{status}。這是移動平均基線，適合初步排班與備貨判斷。"
    if any(k in q for k in ("優惠", "coupon", "促銷", "save50", "free100")):
        c = next(c for c in d['coupons'] if c['code'] == "FREE100")
        return f"FREE100 今日使用率 {c['usage_rate']:.1%}、AOV NT${c['aov']:,}、折扣成本 NT${c['discount_cost']:,}。它的客單價高於 SAVE50，建議先針對高客單商品測試，再以 A/B test 確認增量效果。"
    return "我目前能根據儀表板資料回答：昨日營收變化、明日需求／產能，以及優惠券成效。試著問「明日產能是否足夠？」或「FREE100 表現如何？」"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(BASE / "static"), **kwargs)
    def do_GET(self):
        if urlparse(self.path).path == "/api/dashboard":
            self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers()
            self.wfile.write(json.dumps(calculate(), ensure_ascii=False).encode()); return
        return super().do_GET()
    def do_POST(self):
        if urlparse(self.path).path != "/api/question": self.send_error(404); return
        size = int(self.headers.get("Content-Length", 0)); payload = json.loads(self.rfile.read(size) or b"{}")
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers()
        self.wfile.write(json.dumps({"answer": answer(str(payload.get("question", "")), calculate())}, ensure_ascii=False).encode())


if __name__ == "__main__":
    make_demo_data()
    print("Dashboard: http://127.0.0.1:8080")
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
