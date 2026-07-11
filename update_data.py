# -*- coding: utf-8 -*-
"""ดึงข้อมูลราคารายเดือนจาก Yahoo Finance แปลงเป็น THB แล้วฝังลง index.html
ใช้: python update_data.py   (รันในโฟลเดอร์ dca-calculator)
"""
import json, time, re, sys, os, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch(symbol, range_="30y", retries=3):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1mo&range={range_}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            if data.get("chart", {}).get("error"):
                raise ValueError(f"Yahoo error: {data['chart']['error']}")
            break
        except Exception as e:
            last_err = e
            print(f"  retry {symbol} ({attempt+1}/{retries}): {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    else:
        raise SystemExit(f"ดึง {symbol} ไม่สำเร็จหลัง {retries} ครั้ง: {last_err}")
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

# หุ้นต่างประเทศใช้ ETF (adjclose = รวมเงินปันผล / total return) แล้วแปลงเป็น THB
ASSETS = {
    "VT":      ("VT",        "หุ้นทั้งโลก (VT)",         "USD", "equity_dm"),
    "SP500":   ("SPY",       "S&P 500 (SPY)",            "USD", "equity_dm"),
    "NDX":     ("QQQ",       "Nasdaq 100 (QQQ)",         "USD", "equity_dm"),
    "STOXX":   ("VGK",       "หุ้นยุโรป (VGK)",           "USD", "equity_dm"),
    "N225":    ("EWJ",       "หุ้นญี่ปุ่น (EWJ)",         "USD", "equity_dm"),
    "CSI300":  ("ASHR",      "CSI 300 จีน (ASHR)",       "USD", "equity_em"),
    "HSI":     ("EWH",       "หุ้นฮ่องกง (EWH)",          "USD", "equity_em"),
    "SENSEX":  ("EPI",       "หุ้นอินเดีย (EPI)",         "USD", "equity_em"),
    "AXJ":     ("AAXJ",      "เอเชีย ไม่รวมญี่ปุ่น (AAXJ)", "USD", "equity_em"),
    "SET":     ("TDEX.BK",   "หุ้นไทย SET50 (TDEX)",     "THB", "equity_em"),
    "THBOND":  ("ABFTH.BK",  "ตราสารหนี้ไทย (ABFTH)",    "THB", "bond"),
    "USAGG":   ("AGG",       "ตราสารหนี้สหรัฐฯ (AGG)",   "USD", "bond"),
    "GOLD":    ("GC=F",      "ทองคำ (COMEX)",            "USD", "commodity"),
}
FX_SYMS = {"THB": "THB=X"}

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

def current_embedded(html_path):
    """อ่านข้อมูลที่ฝังอยู่เดิมใน index.html (ถ้ามี) ไว้เทียบกันก่อนเขียนทับ"""
    try:
        with open(html_path, encoding="utf-8") as f:
            m = re.search(r'<script id="mkt" type="application/json">(.*?)</script>', f.read(), re.S)
        return json.loads(m.group(1)) if m and m.group(1).strip() else None
    except Exception:
        return None

def validate(new, old):
    """กันข้อมูลพัง: ถ้าใหม่แย่กว่าเดิมให้ล้มเลิก ไม่ commit ทับของดี"""
    if not new.get("dates") or not new.get("assets"):
        raise SystemExit("ยกเลิก: ข้อมูลใหม่ว่าง")
    if len(new["dates"]) < 60:
        raise SystemExit(f"ยกเลิก: จำนวนเดือนน้อยผิดปกติ ({len(new['dates'])})")
    for k, a in new["assets"].items():
        if not a.get("values") or len(a["values"]) < 12:
            raise SystemExit(f"ยกเลิก: สินทรัพย์ {k} ข้อมูลสั้น/ว่าง")
    if old:
        if len(new["dates"]) < len(old["dates"]):
            raise SystemExit(f"ยกเลิก: เดือนใหม่ ({len(new['dates'])}) < เดิม ({len(old['dates'])})")
        missing = set(old["assets"]) - set(new["assets"])
        if missing:
            raise SystemExit(f"ยกเลิก: สินทรัพย์หายไป {missing}")
    print(f"validate ผ่าน: {len(new['dates'])} เดือน, {len(new['assets'])} สินทรัพย์", file=sys.stderr)

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(here, "index.html")
    old = current_embedded(html_path)
    new = build()
    validate(new, old)
    inject(new, html_path)
