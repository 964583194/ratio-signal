"""
数据源：每个数据都有多个备用接口，并在 data/raw/ 保留本地缓存。

工作方式（get_series）：
  1. 按顺序尝试各个接口，拿到的数据要通过检查：条数够、最新日期不太旧、
     和缓存重叠的日期数值基本一致（防止接口换了口径或返回错数据）。
  2. 第一个通过检查的接口，新数据合并进缓存。只返回最近几百天的接口也能补上最新数据。
  3. 全部接口都失败时，用缓存继续算，并在 data/health.json 记一笔。
  4. 缓存超过 HEALTH_DAYS 天没更新，脚本最后以失败退出，GitHub 会发邮件提醒。
"""
import csv
import datetime as dt
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
HEALTH_DAYS = 12          # 跨长假也够用
HEALTH = {}

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def http(url, referer="", tries=2, timeout=25, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer,
                                               "Accept": "*/*"})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return b if raw else b.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def jget(url, referer=""):
    return json.loads(http(url, referer))


def iso(d):
    d = str(d).strip().replace("/", "-")[:10]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d


# ================================================================ 各接口
def em_kline(secid, beg="19900101"):
    """东方财富日K（收盘价）"""
    q = urllib.parse.urlencode({"secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f53",
                                "klt": "101", "fqt": "0", "beg": beg, "end": "20500101",
                                "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    last = None
    for host in ("push2his", "33.push2his", "63.push2his", "91.push2his"):
        try:
            j = jget(f"https://{host}.eastmoney.com/api/qt/stock/kline/get?" + q, "https://quote.eastmoney.com/")
            return {a.split(",")[0]: float(a.split(",")[1]) for a in (j.get("data") or {}).get("klines") or []}
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def tx_kline(symbol, start_year=2005):
    """腾讯日K，按年分段（A股 sz/sh 前缀，美股 us. 前缀）"""
    out = {}
    for y in range(start_year, dt.date.today().year + 1):
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
               f"{symbol},day,{y}-01-01,{y}-12-31,400,")
        try:
            node = (jget(url, "https://gu.qq.com/").get("data") or {}).get(symbol) or {}
        except Exception:  # noqa: BLE001
            continue
        for row in node.get("day") or node.get("qfqday") or []:
            out[row[0]] = float(row[2])
    return out


def tx_kline2(symbol, n=640):
    """腾讯日K（不复权，最近 n 天，ETF 用）"""
    j = jget(f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,,,{n}", "https://gu.qq.com/")
    node = (j.get("data") or {}).get(symbol) or {}
    return {r[0]: float(r[2]) for r in node.get("day") or []}


def sina_kline(symbol, n=1000):
    """新浪日K（最多约几千天）"""
    url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen={n}")
    rows = json.loads(http(url, "https://finance.sina.com.cn/") or "[]") or []
    return {r["day"][:10]: float(r["close"]) for r in rows}


def cs_perf(code, field="close", start="20100101"):
    """中证指数官网：field=close 收盘，field=peg 市盈率"""
    url = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={code}&startDate={start}&endDate={dt.date.today():%Y%m%d}")
    rows = jget(url, "https://www.csindex.com.cn/").get("data") or []
    return {iso(r["tradeDate"]): float(r[field]) for r in rows if r.get(field) not in (None, "")}


def cni_kline(code, start="2005-01-01"):
    """国证指数官网（深交所指数，如 399673）"""
    url = ("https://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat"
           f"?indexCode={code}&startDate={start}&endDate={dt.date.today()}&frequency=day")
    j = jget(url, "https://www.cnindex.com.cn/")
    data = (j.get("data") or {})
    items, cols = data.get("data") or [], data.get("item") or []
    ci, di = cols.index("closingIndex") if "closingIndex" in cols else 5, cols.index("timestamp") if "timestamp" in cols else 0
    out = {}
    for r in items:
        d = r[di]
        d = dt.datetime.fromtimestamp(d / 1000).strftime("%Y-%m-%d") if isinstance(d, (int, float)) else iso(d)
        out[d] = float(r[ci])
    return out


def stooq(sym):
    txt = http(f"https://stooq.com/q/d/l/?s={sym}&i=d")
    return {r["Date"]: float(r["Close"]) for r in csv.DictReader(io.StringIO(txt)) if r.get("Close")}


def yahoo(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=max&interval=1d"
    r = jget(url)["chart"]["result"][0]
    ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
    return {dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"): float(c) for t, c in zip(ts, cl) if c}


def fred(series):
    txt = http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=60)
    rd = csv.reader(io.StringIO(txt))
    next(rd)
    return {r[0]: float(r[1]) for r in rd if len(r) > 1 and r[1] not in (".", "")}


def em_treasury(col):
    """东方财富中美国债：EMM00166466 中国10年，EMG00001310 美国10年"""
    out, page = {}, 1
    while page < 60:
        q = urllib.parse.urlencode({"reportName": "RPTA_WEB_TREASURYYIELD", "columns": f"SOLAR_DATE,{col}",
                                    "sortColumns": "SOLAR_DATE", "sortTypes": "-1", "pageNumber": page,
                                    "pageSize": "500", "source": "WEB", "client": "WEB"})
        data = (jget("https://datacenter.eastmoney.com/api/data/v1/get?" + q,
                     "https://data.eastmoney.com/").get("result") or {}).get("data") or []
        if not data:
            break
        for r in data:
            if r.get(col) is not None:
                out[r["SOLAR_DATE"][:10]] = float(r[col])
        if data[-1]["SOLAR_DATE"][:4] < "2010":
            break
        page += 1
    return out


def ust_gov(years=2):
    """美国财政部官网 10 年期收益率（最近几年）"""
    out = {}
    for y in range(dt.date.today().year - years + 1, dt.date.today().year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
        for r in csv.DictReader(io.StringIO(http(url))):
            m, d, yy = r["Date"].split("/")
            if r.get("10 Yr"):
                out[f"{yy}-{m}-{d}"] = float(r["10 Yr"])
    return out


def nasdaq_api(sym="NDX", years=3):
    """纳斯达克官网历史行情（最近几年）"""
    end = dt.date.today()
    url = (f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=index"
           f"&fromdate={end - dt.timedelta(days=365 * years)}&limit=9999&todate={end}")
    j = jget(url, "https://www.nasdaq.com/")
    rows = (((j.get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    out = {}
    for r in rows:
        m, d, y = r["date"].split("/")
        out[f"{y}-{m}-{d}"] = float(str(r["close"]).replace(",", ""))
    return out


def sina_us(sym=".ndx"):
    """新浪美股日K"""
    txt = http(f"https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_x=/US_MinKService.getDailyK?symbol={sym}",
               "https://finance.sina.com.cn/")
    m = re.search(r"\((\[.*\])\)", txt, re.S)
    rows = json.loads(m.group(1)) if m else []
    return {r["d"]: float(r["c"]) for r in rows}


def em_lsjz(code, pages=10):
    out = {}
    for p in range(1, pages + 1):
        u = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={p}&pageSize=20"
        rows = (jget(u, "https://fundf10.eastmoney.com/").get("Data") or {}).get("LSJZList") or []
        if not rows:
            break
        out.update({r["FSRQ"]: float(r["DWJZ"]) for r in rows if r.get("DWJZ")})
    return out


def em_pzd(code):
    """天天基金 pingzhongdata：完整单位净值走势"""
    js = http(f"https://fund.eastmoney.com/pingzhongdata/{code}.js", "https://fund.eastmoney.com/")
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", js, re.S)
    rows = json.loads(m.group(1)) if m else []
    return {dt.datetime.utcfromtimestamp(r["x"] / 1000 + 8 * 3600).strftime("%Y-%m-%d"): float(r["y"]) for r in rows}


def sina_nav(code, n=200):
    url = ("https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"
           f"?symbol={code}&datefrom=&dateto=&page=1&num={n}")
    rows = ((jget(url).get("result") or {}).get("data") or {}).get("data") or []
    return {r["fbrq"][:10]: float(r["jjjz"]) for r in rows}


def danjuan_pe(sym):
    j = jget(f"https://danjuanfunds.com/djapi/index_eva/pe_history/{sym}?day=all", "https://danjuanfunds.com/")
    return {dt.datetime.utcfromtimestamp(r["ts"] / 1000 + 8 * 3600).strftime("%Y-%m-%d"): float(r["pe"])
            for r in (j.get("data") or {}).get("index_eva_pe_growths") or []}


# ================================================================ 数据清单：每项 3~5 个接口
CATALOG = {
    "cyb50": ("创业板50 收盘", [
        ("东方财富", lambda: em_kline("0.399673", "20140101")),
        ("国证指数官网", lambda: cni_kline("399673", "2014-01-01")),
        ("腾讯", lambda: tx_kline("sz399673", 2014)),
        ("新浪(近1000天)", lambda: sina_kline("sz399673")),
    ]),
    "hl100": ("红利低波100 收盘", [
        ("中证指数官网", lambda: cs_perf("930955")),
        ("东方财富", lambda: em_kline("2.930955")),
        ("中证指数官网(近两年)", lambda: cs_perf("930955", "close", f"{dt.date.today().year - 1}0101")),
    ]),
    "hl100_pe": ("红利低波100 市盈率", [
        ("中证指数官网", lambda: cs_perf("930955", "peg")),
        ("中证指数官网(近两年)", lambda: cs_perf("930955", "peg", f"{dt.date.today().year - 1}0101")),
    ]),
    "hl100_tr": ("红利低波100 全收益", [
        ("中证指数官网", lambda: cs_perf("H20955")),
        ("东方财富", lambda: em_kline("2.H20955")),
        ("中证指数官网(近两年)", lambda: cs_perf("H20955", "close", f"{dt.date.today().year - 1}0101")),
    ]),
    "kc50": ("科创50 收盘", [
        ("东方财富", lambda: em_kline("1.000688")),
        ("中证指数官网", lambda: cs_perf("000688")),
        ("腾讯", lambda: tx_kline("sh000688", 2019)),
        ("新浪(近1000天)", lambda: sina_kline("sh000688")),
    ]),
    "a500": ("中证A500 收盘", [
        ("东方财富", lambda: em_kline("1.000510", "20050101")),
        ("中证指数官网", lambda: cs_perf("000510")),
        ("新浪(近1000天)", lambda: sina_kline("sh000510")),
        ("腾讯(2024年起)", lambda: tx_kline("sh000510", 2024)),
    ]),
    "pe300": ("沪深300 市盈率", [
        ("中证指数官网", lambda: cs_perf("000300", "peg")),
        ("中证指数官网(近两年)", lambda: cs_perf("000300", "peg", f"{dt.date.today().year - 1}0101")),
    ]),
    "pe_a500": ("中证A500 市盈率", [
        ("中证指数官网", lambda: cs_perf("000510", "peg")),
        ("中证指数官网(近两年)", lambda: cs_perf("000510", "peg", f"{dt.date.today().year - 1}0101")),
    ]),
    "cn10y": ("中国十年国债", [
        ("东方财富", lambda: em_treasury("EMM00166466")),
    ]),
    "us10y": ("美国十年国债", [
        ("东方财富", lambda: em_treasury("EMG00001310")),
        ("美国财政部", lambda: ust_gov()),
        ("美联储FRED", lambda: fred("DGS10")),
    ]),
    "ndx": ("纳指100 收盘", [
        ("腾讯", lambda: tx_kline("us.NDX", 2014)),
        ("新浪", lambda: sina_us(".ndx")),
        ("东方财富", lambda: em_kline("100.NDX100")),
        ("纳斯达克官网(近三年)", lambda: nasdaq_api("NDX")),
        ("美联储FRED", lambda: fred("NASDAQ100")),
    ]),
    "etf513100": ("纳指ETF 513100 收盘", [
        ("东方财富", lambda: em_kline("1.513100", "20240101")),
        ("腾讯", lambda: tx_kline2("sh513100")),
        ("新浪", lambda: sina_kline("sh513100", 600)),
    ]),
    "nav513100": ("纳指ETF 513100 净值", [
        ("天天基金", lambda: em_pzd("513100")),
        ("东方财富", lambda: em_lsjz("513100")),
        ("新浪", lambda: sina_nav("513100")),
    ]),
}

# 和缓存比对时允许的差异：价格类 1%，收益率类按绝对值 0.15 个百分点
TOL = {"cn10y": ("abs", 0.15), "us10y": ("abs", 0.15)}


# ================================================================ 缓存与选择
def _load(key):
    try:
        with open(os.path.join(RAW, f"{key}.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save(key, data):
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, f"{key}.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(data.items())), f, ensure_ascii=False, separators=(",", ":"))


def _check(key, new, cache):
    if not new:
        return "没有数据"
    last = max(new)
    if (dt.date.today() - dt.date.fromisoformat(last)).days > HEALTH_DAYS:
        return f"数据太旧（最新 {last}）"
    common = sorted(set(new) & set(cache))[-60:]
    if common:
        kind, tol = TOL.get(key, ("rel", 0.01))
        bad = 0
        for d in common:
            a, b = new[d], cache[d]
            diff = abs(a - b) if kind == "abs" else abs(a / b - 1) if b else 1
            bad += diff > tol
        if bad > len(common) * 0.2:
            return f"与已有数据对不上（{bad}/{len(common)} 天差异过大）"
    elif cache and len(new) < 30:
        return "条数太少且无法与缓存比对"
    return None


def get_series(key, min_days=200):
    """返回 (数据 dict, 来源说明)。至少返回缓存；缓存也没有才抛错。"""
    name, cands = CATALOG[key]
    cache = _load(key)
    tried = []
    for label, fn in cands:
        try:
            new = fn()
        except Exception as e:  # noqa: BLE001
            tried.append(f"{label}：{type(e).__name__} {str(e)[:60]}")
            continue
        why = _check(key, new, cache)
        if why:
            tried.append(f"{label}：{why}")
            continue
        merged = {**cache, **new}
        if len(merged) < min_days:
            tried.append(f"{label}：合并后只有 {len(merged)} 天")
            continue
        _save(key, merged)
        HEALTH[key] = {"name": name, "source": label, "last": max(merged), "days": len(merged),
                       "failed": tried}
        print(f"[数据] {name}：{label}，{len(new)} 天，最新 {max(new)}" + (f"（跳过：{'；'.join(tried)}）" if tried else ""))
        return merged, label
    if cache:
        HEALTH[key] = {"name": name, "source": "本地缓存", "last": max(cache), "days": len(cache),
                       "failed": tried}
        print(f"[数据] {name}：全部接口失败，使用缓存（最新 {max(cache)}）：{'；'.join(tried)}")
        return cache, "本地缓存"
    HEALTH[key] = {"name": name, "source": None, "last": None, "days": 0, "failed": tried}
    raise RuntimeError(f"{name} 所有接口都失败：{'；'.join(tried)}")


def write_health():
    """写 data/health.json；有数据超过 HEALTH_DAYS 天没更新则返回 False（让任务失败、发邮件）"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    ok = True
    for v in HEALTH.values():
        v["stale_days"] = (now.date() - dt.date.fromisoformat(v["last"])).days if v["last"] else None
        if v["stale_days"] is None or v["stale_days"] > HEALTH_DAYS:
            ok = False
    with open(os.path.join(ROOT, "data", "health.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "ok": ok, "items": HEALTH},
                  f, ensure_ascii=False, indent=1)
    return ok


# ================================================================ 逐个接口体检（手动运行：python sources.py）
if __name__ == "__main__":
    for key, (name, cands) in CATALOG.items():
        for label, fn in cands:
            t = time.time()
            try:
                d = fn()
                k = sorted(d)
                print(f"OK   {name:<16} {label:<12} {len(k):>5} 天 {k[0] if k else '-'} ~ {k[-1] if k else '-'} 最新值 {d[k[-1]] if k else '-'} ({time.time()-t:.1f}s)")
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {name:<16} {label:<12} {type(e).__name__}: {str(e)[:90]}")
