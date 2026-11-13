"""
数据源：每项数据配 3~5 个接口，并在 data/raw/*.csv 保留按行存储的缓存。

工作方式：
  1. 有缓存时只向接口要最近约 60 天的数据（增量更新），没有缓存才拉全量。
  2. 按顺序尝试各接口，新数据要通过检查：最新日期不太旧、和缓存重叠的日期数值一致
     （防止接口换了口径或返回错数据）。第一个通过检查的接口，新数据合并进缓存。
  3. 全部接口失败时用缓存继续算；每次运行每项数据只请求一次（结果在内存里复用）。
  4. 每次运行写 data/health.json；有数据超过 HEALTH_DAYS 天没更新，工作流会失败并发邮件。

手动体检所有接口：python sources.py
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


def fred(series):
    txt = http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=60)
    rd = csv.reader(io.StringIO(txt))
    next(rd)
    return {r[0]: float(r[1]) for r in rd if len(r) > 1 and r[1] not in (".", "")}


def em_treasury(col, since=None):
    """东方财富中美国债：EMM00166466 中国10年，EMG00001310 美国10年。since 之前的页不再翻"""
    stop = since or "2010"
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
        if data[-1]["SOLAR_DATE"][:10] < stop:
            break
        page += 1
    return out


def em_amount(secid, beg="20100101"):
    """东方财富日K 成交额（亿元）"""
    q = urllib.parse.urlencode({"secid": secid, "fields1": "f1", "fields2": "f51,f57", "klt": "101", "fqt": "0",
                                "beg": beg, "end": "20500101", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    last = None
    for host in ("push2his", "33.push2his", "63.push2his"):
        try:
            j = jget(f"https://{host}.eastmoney.com/api/qt/stock/kline/get?" + q, "https://quote.eastmoney.com/")
            return {a.split(",")[0]: float(a.split(",")[1]) / 1e8 for a in (j.get("data") or {}).get("klines") or []}
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def mkt_amount(since=None):
    """沪深两市成交额 = 上证指数 + 深证成指"""
    beg = _ymd(since, "20100101")
    a, b = em_amount("1.000001", beg), em_amount("0.399001", beg)
    return {d: round(a[d] + b[d], 2) for d in a if d in b}


_MARGIN = {}


def em_margin(field, since=None):
    """东方财富 两市融资融券：RZYE 融资余额（亿元），ratio 融资余额 ÷ 流通市值（%）"""
    if since not in _MARGIN:
        stop, out, page = since or "2010", [], 1
        while page < 10:
            q = urllib.parse.urlencode({"reportName": "RPTA_RZRQ_LSHJ", "columns": "DIM_DATE,RZYE,LTSZ", "source": "WEB",
                                        "sortColumns": "DIM_DATE", "sortTypes": "-1", "pageNumber": page, "pageSize": "1000"})
            rows = (jget("https://datacenter-web.eastmoney.com/api/data/v1/get?" + q,
                         "https://data.eastmoney.com/").get("result") or {}).get("data") or []
            if not rows:
                break
            out += rows
            if rows[-1]["DIM_DATE"][:10] < stop:
                break
            page += 1
        _MARGIN[since] = out
    out = {}
    for r in _MARGIN[since]:
        if r.get("RZYE") and r.get("LTSZ"):
            out[r["DIM_DATE"][:10]] = round(r["RZYE"] / 1e8, 2) if field == "RZYE" else round(r["RZYE"] / r["LTSZ"] * 100, 4)
    return out


def dj_pe(code):
    """蛋卷基金 指数市盈率历史（周）"""
    j = jget(f"https://danjuanfunds.com/djapi/index_eva/pe_history/{code}?day=all", "https://danjuanfunds.com/")
    return {dt.datetime.fromtimestamp(x["ts"] / 1000 + 8 * 3600, dt.timezone.utc).date().isoformat(): x["pe"]
            for x in (j.get("data") or {}).get("index_eva_pe_growths") or []}


def ak_pb_below(since=None):
    """乐咕乐股 全部A股破净率（经 AKShare）"""
    import akshare as ak  # noqa: PLC0415  只在需要时导入，没装时走缓存
    df = ak.stock_a_below_net_asset_statistics(symbol="全部A股")
    return {str(r["date"])[:10]: float(r["below_net_asset_ratio"]) for _, r in df.iterrows()
            if not since or str(r["date"])[:10] >= since}


_SSE_DAY = {}


def sse_scale_day(d):
    """上交所 ETF 规模（份）某一天的全部 ETF：{代码: 份额}。带 jsonCallBack 的请求方式（不带会被 403）"""
    if d in _SSE_DAY:
        return _SSE_DAY[d]
    u = ("https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback1&isPagination=true&pageHelp.pageSize=10000"
         "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
         f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}&_={int(time.time() * 1000)}")
    t = http(u, "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/")
    t = t[t.index("(") + 1:t.rindex(")")]
    rows = (json.loads(t).get("pageHelp") or {}).get("data") or json.loads(t).get("result") or []
    _SSE_DAY[d] = {r["SEC_CODE"]: float(r["TOT_VOL"]) * 1e4 for r in rows if r.get("TOT_VOL")}
    return _SSE_DAY[d]


def _wdays(since, back=12):
    """从 since（或今天往前 back 天）到今天的工作日"""
    d0 = dt.date.fromisoformat(since) if since else dt.date.today() - dt.timedelta(days=back)
    out, d = [], d0
    while d <= dt.date.today():
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def sse_shares(code, since):
    out = {}
    for d in _wdays(since)[-10:]:      # 每天只补最近两周，历史已在缓存
        try:
            v = sse_scale_day(d).get(code)
        except Exception:  # noqa: BLE001
            v = None
        if v:
            out[d] = v
    if not out:
        raise RuntimeError("没有取到")
    return out


def ak_sse_shares(code, since):
    import akshare as ak  # noqa: PLC0415
    out = {}
    for d in _wdays(since)[-8:]:
        try:
            df = ak.fund_etf_scale_sse(date=d.replace("-", ""))
        except Exception:  # noqa: BLE001
            continue
        x = df[df["基金代码"].astype(str) == code]
        if len(x):
            out[d] = float(x["基金份额"].iloc[0])
    if not out:
        raise RuntimeError("没有取到")
    return out


def ak_szse_shares(code, since):
    """深交所基金规模日频（AKShare 封装，一次最多 6 个月）"""
    import akshare as ak  # noqa: PLC0415
    d0 = dt.date.fromisoformat(since) if since else dt.date.today() - dt.timedelta(days=150)
    last = None
    for k in range(4):       # 深交所接口偶尔断开连接，多试几次
        try:
            df = ak.fund_scale_daily_szse(start_date=d0.strftime("%Y%m%d"), end_date=dt.date.today().strftime("%Y%m%d"))
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (k + 1))
    else:
        raise last
    x = df[df["基金代码"].astype(str) == code]
    out = {str(r["日期"])[:10]: float(r["基金份额"]) for _, r in x.iterrows()}
    if not out:
        raise RuntimeError("没有取到")
    return out


def szse_shares_now(code, since):
    """深交所 ETF 列表里的“当前规模(份)”，只有最新一天"""
    import io as _io  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    b = http("https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1945&TABKEY=tab1",
             "https://www.szse.cn/", raw=True)
    df = pd.read_excel(_io.BytesIO(b), dtype={"证券代码": str})
    x = df[df["证券代码"].astype(str).str.zfill(6) == code]
    v = float(str(x["当前规模(份)"].iloc[0]).replace(",", ""))
    # “当前规模”是上一个交易日的份额（2026-11-10 下载的值和 11-09 的日频数据完全相同）
    d = dt.date.today() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return {d.isoformat(): v}


def ak_buffett(since):
    """巴菲特指标：A 股总市值 ÷ GDP（乐咕乐股，经 AKShare）"""
    import akshare as ak  # noqa: PLC0415
    df = ak.stock_buffett_index_lg()
    out = {str(r["日期"])[:10]: float(r["总市值"]) / float(r["GDP"]) for _, r in df.iterrows() if float(r["GDP"] or 0) > 0}
    if not out:
        raise RuntimeError("没有取到")
    return out


def _month(s):
    """'2026年09月份' / '2026.9' / '202609' → '2026-09-01'（月度数据用当月 1 号表示）"""
    import re  # noqa: PLC0415
    m = re.match(r"(\d{4})\D*?(\d{1,2})\D*$", str(s).replace("月份", "").replace("月", "")) or re.match(r"(\d{4})(\d{2})", str(s))
    return f"{m.group(1)}-{int(m.group(2)):02d}-01"


def ak_money(col):
    """M1 同比（%），月度（东方财富，经 AKShare）"""
    def f(since):
        import akshare as ak  # noqa: PLC0415
        df = ak.macro_china_money_supply()
        out = {_month(r["月份"]): float(r[col]) for _, r in df.iterrows() if str(r[col]) not in ("", "nan", "None")}
        if not out:
            raise RuntimeError("没有取到")
        return out
    return f


def ak_loan(since):
    """新增人民币贷款（亿元，当月），月度（东方财富，经 AKShare）"""
    import akshare as ak  # noqa: PLC0415
    df = ak.macro_china_new_financial_credit()
    out = {_month(r["月份"]): float(r["当月"]) for _, r in df.iterrows() if str(r["当月"]) not in ("", "nan", "None")}
    if not out:
        raise RuntimeError("没有取到")
    return out


def ust_real10(since):
    """美国 10 年期实际利率（财政部每日实际收益率曲线），增量时只取今年和去年"""
    y1 = dt.date.today().year
    y0 = y1 - 1 if since else 2010
    out = {}
    for y in range(y0, y1 + 1):
        txt = http(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                   f"?type=daily_treasury_real_yield_curve&field_tdr_date_value={y}&page&_format=csv", timeout=60)
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get("10 YR"):
                m, d, yy = r["Date"].split("/")
                out[f"{yy}-{m}-{d}"] = float(r["10 YR"])
    if not out:
        raise RuntimeError("没有取到")
    return out


def ak_spdr(since):
    """SPDR 黄金 ETF 持仓（吨），经 AKShare"""
    import akshare as ak  # noqa: PLC0415
    df = ak.macro_cons_gold()
    out = {str(r["日期"])[:10]: float(r["总库存"]) for _, r in df.iterrows() if str(r["总库存"]) not in ("", "nan")}
    if not out:
        raise RuntimeError("没有取到")
    return out


def ak_ag0(since):
    """上期所白银主力合约收盘（元/千克），经 AKShare"""
    import akshare as ak  # noqa: PLC0415
    df = ak.futures_main_sina(symbol="AG0")
    out = {str(r["日期"])[:10]: float(r["收盘价"]) for _, r in df.iterrows()}
    if not out:
        raise RuntimeError("没有取到")
    return {k: v for k, v in out.items() if not since or k >= since} or out


# ================================================================ 备用数据源（主源失败时才用）
def calibrated(key, fn):
    """口径不同但比例稳定的备用源：用和缓存重叠的最近 5 天算比例，折算成主源口径，只补最近 5 天及以后的数据。
    （比如沪深300 市盈率：比例在一个季度内很稳，季报公布后会跳一档，所以只用最近几天；主源停的期间又碰上季报，会差几个百分点）"""
    def f(since):
        new, old = fn(since), load_cache(key)
        common = [d for d in sorted(set(new) & set(old)) if new[d]][-5:]
        if len(common) < 3:
            raise RuntimeError("和缓存重叠太少，没法折算口径")
        ks = sorted(old[d] / new[d] for d in common)
        k = ks[len(ks) // 2]
        return {d: v * k for d, v in new.items() if d >= common[0]}
    return f


def csi_value(code, col="市盈率1"):
    """中证指数官网日度指标文件（近 20 个交易日），经 AKShare"""
    def f(since):
        import akshare as ak  # noqa: PLC0415
        df = ak.stock_zh_index_value_csindex(symbol=code)
        return {str(r["日期"])[:10]: float(r[col]) for _, r in df.iterrows() if str(r[col]) not in ("", "nan")}
    return f


def chinabond_10y(since):
    """中债国债收益率曲线 10 年（中国债券信息网，经 AKShare），一次最多取一年"""
    import akshare as ak  # noqa: PLC0415
    y1 = dt.date.today().year
    y0 = int(since[:4]) if since else 2010
    out = {}
    for y in range(y0, y1 + 1):
        end = f"{y}1231" if y < y1 else dt.date.today().strftime("%Y%m%d")
        df = ak.bond_china_yield(start_date=f"{y}0101", end_date=end)
        df = df[df["曲线名称"].astype(str).str.contains("国债")]
        out.update({str(r["日期"])[:10]: float(r["10年"]) for _, r in df.iterrows() if str(r["10年"]) not in ("", "nan")})
    return out


def ak_cn10y(since):
    """AKShare 中美国债收益率：中国 10 年"""
    import akshare as ak  # noqa: PLC0415
    df = ak.bond_zh_us_rate(start_date=(since or "2010-01-01").replace("-", ""))
    return {str(r["日期"])[:10]: float(r["中国国债收益率10年"]) for _, r in df.iterrows() if str(r["中国国债收益率10年"]) not in ("", "nan")}


def em_pb_snapshot(since):
    """用东方财富全市场行情（市净率 f23）自己算当天的破净率：0 < 市净率 < 1 的股票占比"""
    n = below = 0
    for pn in range(1, 80):
        q = urllib.parse.urlencode({"pn": pn, "pz": 200, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12",
                                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23", "fields": "f12,f23", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
        d = None
        for k in range(3):
            try:
                d = jget("https://push2.eastmoney.com/api/qt/clist/get?" + q, "https://quote.eastmoney.com/")
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 * (k + 1))
        rows = ((d or {}).get("data") or {}).get("diff") or []
        if not rows:
            break
        for r in rows:
            p = r.get("f23")
            if isinstance(p, (int, float)):
                n += 1
                below += 0 < p < 1
    if n < 3000:
        raise RuntimeError(f"只有 {n} 只股票有市净率")
    d = dt.date.today()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return {d.isoformat(): below / n}


def ex_margin(since):
    """上交所 + 深交所 融资余额（亿元），经 AKShare；只取最近 40 天"""
    import akshare as ak  # noqa: PLC0415
    beg = dt.date.today() - dt.timedelta(days=40)
    a = ak.stock_margin_sse(start_date=beg.strftime("%Y%m%d"), end_date=dt.date.today().strftime("%Y%m%d"))
    out = {}
    for _, r in a.iterrows():
        d = str(r["信用交易日期"])
        d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        try:
            b = ak.stock_margin_szse(date=d.replace("-", ""))
            out[d] = (float(r["融资余额"]) + float(b["融资余额"].iloc[0]) * 1e8) / 1e8
        except Exception:  # noqa: BLE001
            continue
    if not out:
        raise RuntimeError("没有取到")
    return out


def ak_m1_b(since):
    """M1 同比（AKShare 另一个货币供应接口）"""
    import akshare as ak  # noqa: PLC0415
    df = ak.macro_china_supply_of_money()
    c = "货币(狭义货币M1)同比增长"
    return {_month(r["统计时间"]): float(r[c]) for _, r in df.iterrows() if str(r[c]) not in ("", "nan", "None")}


def sge_ag(since):
    """上海黄金交易所 Ag(T+D) 收盘（元/千克），经 AKShare"""
    import akshare as ak  # noqa: PLC0415
    df = ak.spot_hist_sge(symbol="Ag(T+D)")
    return {str(r["date"])[:10]: float(r["close"]) for _, r in df.iterrows() if not since or str(r["date"])[:10] >= since}


def em_cap300(since):
    """沪深300 流通市值（元，东方财富，只有当天）"""
    out = {}
    for sec in ("1.000300", "90.BK0500"):
        try:
            j = jget(f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec}&fields=f117,f124", "https://quote.eastmoney.com/")
            v, ts = j["data"]["f117"], j["data"].get("f124")
            if v:
                d = dt.datetime.utcfromtimestamp(ts + 8 * 3600).date() if ts else dt.date.today()
                out[d.isoformat()] = float(v)
                return out
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("没有取到")


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


def em_lsjz(code, pages=10, field="DWJZ"):
    """天天基金历史净值表；field="LJJZ" 取累计净值（分红加回）"""
    out = {}
    for p in range(1, pages + 1):
        u = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={p}&pageSize=20"
        rows = (jget(u, "https://fundf10.eastmoney.com/").get("Data") or {}).get("LSJZList") or []
        if not rows:
            break
        out.update({r["FSRQ"]: float(r[field]) for r in rows if r.get(field)})
    return out


def _ms(x):
    return dt.datetime.utcfromtimestamp(x / 1000 + 8 * 3600).strftime("%Y-%m-%d")


def em_pzd(code):
    """天天基金 pingzhongdata：完整单位净值走势"""
    js = http(f"https://fund.eastmoney.com/pingzhongdata/{code}.js", "https://fund.eastmoney.com/")
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", js, re.S)
    rows = json.loads(m.group(1)) if m else []
    return {_ms(r["x"]): float(r["y"]) for r in rows}


def em_pzd_acc(code):
    """天天基金 pingzhongdata：完整累计净值走势（分红加回，用于算回撤和年线）"""
    js = http(f"https://fund.eastmoney.com/pingzhongdata/{code}.js", "https://fund.eastmoney.com/")
    m = re.search(r"Data_ACWorthTrend\s*=\s*(\[.*?\]);", js, re.S)
    rows = json.loads(m.group(1)) if m else []
    return {_ms(r[0]): float(r[1]) for r in rows if r and r[1] is not None}


def sina_nav(code, n=200, field="jjjz"):
    url = ("https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"
           f"?symbol={code}&datefrom=&dateto=&page=1&num={n}")
    rows = ((jget(url).get("result") or {}).get("data") or {}).get("data") or []
    return {r["fbrq"][:10]: float(r[field]) for r in rows if r.get(field)}


def fund_acc(code):
    """海外小仓位基金：累计净值，三个接口互为备用"""
    return [("天天基金", lambda s: em_pzd_acc(code)),
            ("东方财富", lambda s: em_lsjz(code, 4 if s else 250, "LJJZ")),
            ("新浪", lambda s: sina_nav(code, 60 if s else 5000, "ljjz"))]


# ================================================================ 数据清单：每项 3~5 个接口
# 每个接口是 f(since)：since 为 None 时拉全量，否则只拉 since（YYYY-MM-DD）之后的数据
def _ymd(s, full):
    return s.replace("-", "") if s else full


def _year(s, full):
    return int(s[:4]) if s else full


CATALOG = {
    "cyb50": ("创业板50 收盘", 2500, [
        ("东方财富", lambda s: em_kline("0.399673", _ymd(s, "20140101"))),
        ("国证指数官网", lambda s: cni_kline("399673", s or "2014-01-01")),
        ("腾讯", lambda s: tx_kline("sz399673", _year(s, 2014))),
        ("新浪(近1000天)", lambda s: sina_kline("sz399673", 120 if s else 1000)),
    ]),
    "hl100": ("红利低波100 收盘", 2500, [
        ("中证指数官网", lambda s: cs_perf("930955", "close", _ymd(s, "20100101"))),
        ("东方财富", lambda s: em_kline("2.930955", _ymd(s, "19900101"))),
    ]),
    "hl100_pe": ("红利低波100 市盈率", 2000, [
        ("中证指数官网", lambda s: cs_perf("930955", "peg", _ymd(s, "20100101"))),
        ("中证日度指标", csi_value("930955")),
    ]),
    "hl100_tr": ("红利低波100 全收益", 2500, [
        ("中证指数官网", lambda s: cs_perf("H20955", "close", _ymd(s, "20100101"))),
        ("东方财富", lambda s: em_kline("2.H20955", _ymd(s, "19900101"))),
    ]),
    "kc50": ("科创50 收盘", 1500, [
        ("东方财富", lambda s: em_kline("1.000688", _ymd(s, "19900101"))),
        ("中证指数官网", lambda s: cs_perf("000688", "close", _ymd(s, "20100101"))),
        ("腾讯", lambda s: tx_kline("sh000688", _year(s, 2019))),
        ("新浪(近1000天)", lambda s: sina_kline("sh000688", 120 if s else 1000)),
    ]),
    "a500": ("中证A500 收盘", 3000, [
        ("东方财富", lambda s: em_kline("1.000510", _ymd(s, "20050101"))),
        ("中证指数官网", lambda s: cs_perf("000510", "close", _ymd(s, "20100101"))),
        ("新浪(近1000天)", lambda s: sina_kline("sh000510", 120 if s else 1000)),
        ("腾讯(2024年起)", lambda s: tx_kline("sh000510", _year(s, 2024))),
    ]),
    "hs300": ("沪深300 收盘", 4000, [
        ("东方财富", lambda s: em_kline("1.000300", _ymd(s, "20050101"))),
        ("中证指数官网", lambda s: cs_perf("000300", "close", _ymd(s, "20050101"))),
        ("腾讯", lambda s: tx_kline("sh000300", _year(s, 2005))),
        ("新浪(近1000天)", lambda s: sina_kline("sh000300", 120 if s else 1000)),
    ]),
    "pe300": ("沪深300 市盈率", 2500, [
        ("中证指数官网", lambda s: cs_perf("000300", "peg", _ymd(s, "20100101"))),
        ("中证日度指标（折算）", calibrated("pe300", csi_value("000300"))),
    ]),
    "pe_a500": ("中证A500 市盈率", 100, [
        ("中证指数官网", lambda s: cs_perf("000510", "peg", _ymd(s, "20100101"))),
        ("中证日度指标（折算）", calibrated("pe_a500", csi_value("000510"))),
    ]),
    "cn10y": ("中国十年国债", 2500, [
        ("东方财富", lambda s: em_treasury("EMM00166466", s)),
        ("中债", chinabond_10y),
        ("AKShare 中美国债", ak_cn10y),
    ]),
    "us10y": ("美国十年国债", 400, [
        ("东方财富", lambda s: em_treasury("EMG00001310", s)),
        ("美国财政部", lambda s: ust_gov(1 if s else 2)),
        ("美联储FRED", lambda s: fred("DGS10")),
    ]),
    "ndx": ("纳指100 收盘", 2500, [
        ("腾讯", lambda s: tx_kline("us.NDX", _year(s, 2014))),
        ("新浪", lambda s: sina_us(".ndx")),
        ("东方财富", lambda s: em_kline("100.NDX100", _ymd(s, "19900101"))),
        ("纳斯达克官网(近三年)", lambda s: nasdaq_api("NDX", 1 if s else 3)),
        ("美联储FRED", lambda s: fred("NASDAQ100")),
    ]),
    "gold": ("黄金ETF 518880 收盘", 2000, [
        ("东方财富", lambda s: em_kline("1.518880", _ymd(s, "20130101"))),
        ("腾讯", lambda s: tx_kline2("sh518880", 60 if s else 3500)),
        ("新浪(近1000天)", lambda s: sina_kline("sh518880", 120 if s else 1000)),
    ]),
    # ---- 以下为参考指标（见底评分），失败不影响主流程
    "pb_below": ("全A破净率", 2000, [("乐咕乐股(AKShare)", ak_pb_below), ("东方财富快照自算", em_pb_snapshot)]),
    "margin": ("两市融资余额", 2000, [("东方财富", lambda s: em_margin("RZYE", s)), ("上交所+深交所", ex_margin)]),
    "margin_ratio": ("融资余额占流通市值", 2000, [("东方财富", lambda s: em_margin("ratio", s))]),
    "mkt_amt": ("两市成交额", 2000, [("东方财富", mkt_amount)]),
    "pe_cyb": ("创业板指市盈率(周)", 400, [("蛋卷基金", lambda s: dj_pe("SZ399006"))]),
    "pe_kc": ("科创50市盈率(周)", 250, [("蛋卷基金", lambda s: dj_pe("SH000688"))]),
    "sh510300": ("华泰柏瑞沪深300ETF 份额", 200, [("上交所", lambda s: sse_shares("510300", s)), ("AKShare", lambda s: ak_sse_shares("510300", s))]),
    "sh510310": ("易方达沪深300ETF 份额", 200, [("上交所", lambda s: sse_shares("510310", s)), ("AKShare", lambda s: ak_sse_shares("510310", s))]),
    "sh510330": ("华夏沪深300ETF 份额", 200, [("上交所", lambda s: sse_shares("510330", s)), ("AKShare", lambda s: ak_sse_shares("510330", s))]),
    "sz159919": ("嘉实沪深300ETF 份额", 200, [("深交所日频", lambda s: ak_szse_shares("159919", s)), ("深交所当前", lambda s: szse_shares_now("159919", s))]),
    "unav510300": ("510300 单位净值", 200, [("天天基金", lambda s: em_pzd("510300")), ("东方财富", lambda s: em_lsjz("510300", 3 if s else 60)), ("新浪", lambda s: sina_nav("510300", 60 if s else 1000))]),
    "unav510310": ("510310 单位净值", 200, [("天天基金", lambda s: em_pzd("510310")), ("东方财富", lambda s: em_lsjz("510310", 3 if s else 60)), ("新浪", lambda s: sina_nav("510310", 60 if s else 1000))]),
    "unav510330": ("510330 单位净值", 200, [("天天基金", lambda s: em_pzd("510330")), ("东方财富", lambda s: em_lsjz("510330", 3 if s else 60)), ("新浪", lambda s: sina_nav("510330", 60 if s else 1000))]),
    "unav159919": ("159919 单位净值", 200, [("天天基金", lambda s: em_pzd("159919")), ("东方财富", lambda s: em_lsjz("159919", 3 if s else 60)), ("新浪", lambda s: sina_nav("159919", 60 if s else 1000))]),
    "cap300": ("沪深300 流通市值", 1, [("东方财富", em_cap300)]),
    "buffett": ("巴菲特指标（总市值÷GDP）", 200, [("乐咕乐股", ak_buffett)]),
    # ---- 宏观（月度，市场温度的“方向”用；每月中旬公布上个月）
    "m1": ("M1 同比", 100, [("东方财富", ak_money("货币(M1)-同比增长")), ("AKShare 货币供应", ak_m1_b)]),
    "loan": ("新增人民币贷款", 100, [("东方财富", ak_loan)]),     # 另一个接口（金十）口径不同，对不上，不用
    # ---- 黄金分析页
    "real10": ("美国 10 年期实际利率", 1000, [("美国财政部", ust_real10)]),
    "spdr": ("SPDR 黄金 ETF 持仓", 1000, [("AKShare", ak_spdr)]),
    "ag0": ("白银期货主力", 1000, [("新浪", ak_ag0), ("上金所 Ag(T+D)", sge_ag)]),
    "etf513100": ("纳指ETF 513100 收盘", 100, [
        ("东方财富", lambda s: em_kline("1.513100", _ymd(s, "20240101"))),
        ("腾讯", lambda s: tx_kline2("sh513100", 60 if s else 640)),
        ("新浪", lambda s: sina_kline("sh513100", 60 if s else 600)),
    ]),
    "nav513100": ("纳指ETF 513100 净值", 100, [
        ("天天基金", lambda s: em_pzd("513100")),
        ("东方财富", lambda s: em_lsjz("513100", 3 if s else 10)),
        ("新浪", lambda s: sina_nav("513100", 60 if s else 200)),
    ]),
    # ---- 海外小仓位（只作提醒，失败不算异常）
    "nav006555": ("浦银全球智能科技 累计净值", 200, fund_acc("006555")),
    "nav539002": ("建信新兴市场混合 累计净值", 200, fund_acc("539002")),
    "nav007280": ("摩根日本精选 累计净值", 200, fund_acc("007280")),
    "nav021189": ("南方亚太精选ETF联接 累计净值", 200, fund_acc("021189")),
    "etf159687": ("亚太精选ETF 159687 收盘", 100, [
        ("东方财富", lambda s: em_kline("0.159687", _ymd(s, "20230101"))),
        ("腾讯", lambda s: tx_kline2("sz159687", 60 if s else 640)),
        ("新浪", lambda s: sina_kline("sz159687", 60 if s else 600)),
    ]),
    "nav159687": ("亚太精选ETF 159687 净值", 100, [
        ("天天基金", lambda s: em_pzd("159687")),
        ("东方财富", lambda s: em_lsjz("159687", 3 if s else 10)),
        ("新浪", lambda s: sina_nav("159687", 60 if s else 200)),
    ]),
}

# 和缓存比对时允许的差异：价格类相对 1%，收益率类绝对 0.15 个百分点
OVERSEAS_KEYS = {"nav006555", "nav539002", "nav007280", "nav021189", "etf159687", "nav159687"}
ETF300_KEYS = {"buffett", "sh510300", "sh510310", "sh510330", "sz159919", "unav510300", "unav510310", "unav510330", "unav159919", "cap300"}
MONTHLY_KEYS = {"m1", "loan"}     # 月度数据：最新一条本来就是一个多月前的
GOLD_KEYS = {"real10", "spdr", "ag0"}
REF_KEYS = {"pb_below", "margin", "margin_ratio", "mkt_amt", "pe_cyb", "pe_kc"} | OVERSEAS_KEYS | ETF300_KEYS | MONTHLY_KEYS | GOLD_KEYS
TOL = {"cn10y": ("abs", 0.15), "us10y": ("abs", 0.15), "m1": ("abs", 0.5), "loan": ("rel", 0.05), "real10": ("abs", 0.15), "pb_below": ("abs", 0.01), "ag0": ("rel", 0.02)}
INCR_DAYS = 60          # 增量更新时回看的天数（同时用于和缓存比对）


# ================================================================ 缓存（按行 CSV）
def _path(key):
    return os.path.join(RAW, f"{key}.csv")


def load_cache(key):
    out = {}
    try:
        with open(_path(key), encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0][:1].isdigit():
                    out[row[0]] = float(row[1])
    except FileNotFoundError:
        old = os.path.join(RAW, f"{key}.json")          # 旧版 JSON 缓存，自动迁移
        if os.path.exists(old):
            with open(old, encoding="utf-8") as f:
                out = {k: float(v) for k, v in json.load(f).items()}
    return out


def save_cache(key, data):
    os.makedirs(RAW, exist_ok=True)
    with open(_path(key), "w", encoding="utf-8", newline="") as f:
        f.write("date,value\n")
        for d in sorted(data):
            f.write(f"{d},{data[d]:.10g}\n")
    old = os.path.join(RAW, f"{key}.json")
    if os.path.exists(old):
        os.remove(old)


def _check(key, new, cache, incremental):
    if not new:
        return "没有数据"
    last = max(new)
    if (dt.date.today() - dt.date.fromisoformat(last)).days > (80 if key in MONTHLY_KEYS else HEALTH_DAYS):
        return f"数据太旧（最新 {last}）"
    common = sorted(set(new) & set(cache))[-INCR_DAYS:]
    if common:
        kind, tol = TOL.get(key, ("rel", 0.01))
        bad = 0
        for d in common:
            a, b = new[d], cache[d]
            diff = abs(a - b) if kind == "abs" else abs(a / b - 1) if b else 1
            bad += diff > tol
        if bad > len(common) * 0.2:
            return f"与已有数据对不上（{bad}/{len(common)} 天差异过大）"
    elif cache and len(new) <= 3:     # 只给当天值的接口（如流通市值）：和缓存最新一天比，差太多才拒绝
        a, b = new[last], cache[max(cache)]
        if b and abs(a / b - 1) > 0.15:
            return f"和缓存最新值差 {abs(a / b - 1):.0%}，无法核对"
    elif cache:
        return "和缓存没有重叠的日期，无法核对"
    return None


_MEMO = {}


def get_series(key, min_days=None):
    """返回 (数据 dict, 来源说明)。同一次运行里每项数据只请求一次。"""
    if key in _MEMO:
        return _MEMO[key]
    name, need, cands = CATALOG[key]
    need = min_days or need
    cache = load_cache(key)
    incremental = len(cache) >= need
    since = (dt.date.fromisoformat(max(cache)) - dt.timedelta(days=INCR_DAYS)).isoformat() if incremental else None
    tried = []
    # 中证官网有时会好几天不更新某个指数（不报错、只是没有新日期）：主源落后于最近一个交易日时，再试备用源，取最新的
    lagcheck = cands[0][0] == "中证指数官网" and len(cands) > 1
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    want = now.date() if now.hour >= 18 else now.date() - dt.timedelta(days=1)
    while want.weekday() >= 5:
        want -= dt.timedelta(days=1)
    best = None
    for k, (label, fn) in enumerate(cands):
        try:
            new = fn(since)
        except Exception as e:  # noqa: BLE001
            tried.append(f"{label}：{type(e).__name__} {str(e)[:60]}")
            continue
        why = _check(key, new, cache, incremental)
        if why:
            tried.append(f"{label}：{why}")
            continue
        if lagcheck and max(new) < want.isoformat():
            if best is None or max(new) > max(best[1]):
                best = (label, new)
            tried.append(f"{label}：最新只到 {max(new)}")
            if k < len(cands) - 1:
                continue
        if best and max(best[1]) >= max(new):
            label, new = best
        merged = {**cache, **new}
        if len(merged) < need:
            tried.append(f"{label}：合并后只有 {len(merged)} 天")
            continue
        changed = merged != cache
        if changed:
            save_cache(key, merged)
        HEALTH[key] = {"name": name, "source": label, "mode": "增量" if incremental else "全量",
                       "last": max(merged), "days": len(merged), "failed": tried}
        print(f"[数据] {name}：{label}（{'增量' if incremental else '全量'}），收到 {len(new)} 天，最新 {max(new)}"
              + ("" if changed else "，无变化") + (f"（跳过：{'；'.join(tried)}）" if tried else ""))
        _MEMO[key] = (merged, label)
        return _MEMO[key]
    if best:          # 备用源都失败，用主源（虽然落后一点）
        label, new = best
        merged = {**cache, **new}
        if merged != cache:
            save_cache(key, merged)
        HEALTH[key] = {"name": name, "source": label, "mode": "增量" if incremental else "全量",
                       "last": max(merged), "days": len(merged), "failed": tried}
        print(f"[数据] {name}：{label}，最新 {max(new)}（备用源也没有更新的：{'；'.join(tried)}）")
        _MEMO[key] = (merged, label)
        return _MEMO[key]
    if cache:
        HEALTH[key] = {"name": name, "source": "本地缓存", "mode": "缓存", "last": max(cache),
                       "days": len(cache), "failed": tried}
        print(f"[数据] {name}：全部接口失败，使用缓存（最新 {max(cache)}）：{'；'.join(tried)}")
        _MEMO[key] = (cache, "本地缓存")
        return _MEMO[key]
    HEALTH[key] = {"name": name, "source": None, "mode": None, "last": None, "days": 0, "failed": tried}
    raise RuntimeError(f"{name} 所有接口都失败：{'；'.join(tried)}")


def refresh_all():
    """逐项刷新全部数据。返回本次是否有任何数据变化。"""
    before = {k: load_cache(k) for k in CATALOG}
    for key in CATALOG:
        try:
            get_series(key)
        except Exception as e:  # noqa: BLE001
            print(f"[数据] {e}")
    return any(load_cache(k) != before[k] for k in CATALOG)


def write_health():
    """写 data/health.json；有数据超过 HEALTH_DAYS 天没更新则返回 False"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    ok = True
    for k, v in HEALTH.items():
        v["stale_days"] = (now.date() - dt.date.fromisoformat(v["last"])).days if v["last"] else None
        v["ref"] = k in REF_KEYS          # 参考指标过期不算异常
        if not v["ref"] and (v["stale_days"] is None or v["stale_days"] > HEALTH_DAYS):
            ok = False
    with open(os.path.join(ROOT, "data", "health.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "ok": ok, "items": HEALTH},
                  f, ensure_ascii=False, indent=1)
    return ok


# ================================================================ 逐个接口体检（手动运行：python sources.py）
if __name__ == "__main__":
    for key, (name, _, cands) in CATALOG.items():
        for label, fn in cands:
            t = time.time()
            try:
                d = fn(None)
                k = sorted(d)
                print(f"OK   {name:<16} {label:<12} {len(k):>5} 天 {k[0] if k else '-'} ~ {k[-1] if k else '-'} 最新值 {d[k[-1]] if k else '-'} ({time.time()-t:.1f}s)")
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {name:<16} {label:<12} {type(e).__name__}: {str(e)[:90]}")
