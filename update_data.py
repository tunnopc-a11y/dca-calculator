# -*- coding: utf-8 -*-
"""ดึงข้อมูลราคารายเดือนจาก Yahoo Finance แปลงเป็น THB แล้วฝังลง index.html
ใช้: python update_data.py   (รันในโฟลเดอร์ dca-calculator)
"""
import json, time, re, sys, os, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch(symbol, range_="30y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1mo&range={range_}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    quote = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    closes = adj if adj else quote["close"]
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        ym = time.strftime("%Y-%m", time.gmtime(t))
        out[ym] = c
    return out

ASSETS = {
    "SP500":   ("^GSPC",     "S&P 500 (สหรัฐฯ)",        "USD", "equity_dm"),
    "NDX":     ("^NDX",      "Nasdaq 100 (สหรัฐฯ)",     "USD", "equity_dm"),
    "STOXX":   ("^STOXX",    "STOXX Europe 600",         "EUR", "equity_dm"),
    "N225":    ("^N225",     "Nikkei 225 (ญี่ปุ่น)",     "JPY", "equity_dm"),
    "CSI300":  ("ASHR",      "CSI 300 จีน (ASHR)",       "USD", "equity_em"),
    "HSI":     ("^HSI",      "Hang Seng (ฮ่องกง)",       "HKD", "equity_em"),
    "SENSEX":  ("^BSESN",    "SENSEX (อินเดีย)",         "INR", "equity_em"),
    "AXJ":     ("AAXJ",      "เอเชีย ไม่รวมญี่ปุ่น (AAXJ)", "USD", "equity_em"),
    "SET":     ("TDEX.BK",   "หุ้นไทย SET50 (TDEX)",     "THB", "equity_em"),
    "THBOND":  ("ABFTH.BK",  "ตราสารหนี้ไทย (ABFTH)",    "THB", "bond"),
    "USAGG":   ("AGG",       "ตราสารหนี้สหรัฐฯ (AGG)",   "USD", "bond"),
    "GOLD":    ("GC=F",      "ทองคำ (COMEX)",            "USD", "commodity"),
}
FX_SYMS = {"THB": "THB=X", "JPY": "JPY=X", "HKD": "HKD=X", "CNY": "CNY=X", "INR": "INR=X", "EUR": "EURUSD=X"}

def build():
    fx = {}
    for ccy, sym in FX_SYMS.items():
        fx[ccy] = fetch(sym)
        print(f"FX {ccy}: {len(fx[ccy])} months", file=sys.stderr)

    def to_thb(price, ccy, ym):
        if ccy == "THB":
            return price
        usdthb = fx["THB"].get(ym)
        if usdthb is None:
            return None
        if ccy == "USD":
            return price * usdthb
        if ccy == "EUR":
            eurusd = fx["EUR"].get(ym)
            return price * eurusd * usdthb if eurusd else None
        usdccy = fx[ccy].get(ym)
        return price / usdccy * usdthb if usdccy else None

    series = {}
    for key, (sym, name, ccy, klass) in ASSETS.items():
        raw = fetch(sym)
        thb = {}
        for ym, p in raw.items():
            v = to_thb(p, ccy, ym)
            if v is not None and v > 0:
                thb[ym] = v
        months = sorted(thb)
        series[key] = {"name": name, "ccy": ccy, "cls": klass, "sym": sym,
                       "months": months, "values": [thb[m] for m in months]}
        print(f"{key:8s} {sym:10s} {len(months)} months  {months[0]} -> {months[-1]}", file=sys.stderr)
        time.sleep(0.5)

    all_months = sorted(set(m for s in series.values() for s_m in [s["months"]] for m in s_m))
    out = {"dates": all_months, "assets": {}}
    for key, s in series.items():
        idx0 = all_months.index(s["months"][0])
        vmap = dict(zip(s["months"], s["values"]))
        vals, last = [], None
        for m in all_months[idx0:]:
            v = vmap.get(m, last)  # forward-fill gaps
            vals.append(v)
            last = v
        base = vals[0]
        out["assets"][key] = {"name": s["name"], "ccy": s["ccy"], "cls": s["cls"], "sym": s["sym"],
                              "offset": idx0,
                              "values": [round(v / base * 100, 4) for v in vals]}
    return out

def inject(data, html_path):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new, n = re.subn(
        r'(<script id="mkt" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + payload + m.group(2),
        html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("ไม่พบ <script id=\"mkt\"> ใน " + html_path)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"injected {len(payload):,} bytes into {html_path}  "
          f"({len(data['dates'])} months {data['dates'][0]} -> {data['dates'][-1]})", file=sys.stderr)

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    inject(build(), os.path.join(here, "index.html"))
