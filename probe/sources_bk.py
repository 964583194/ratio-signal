"""探测备用数据源：每个候选取一次，和仓库里现有缓存对比重叠日期"""
import sys, json, statistics as st, datetime as dt, re, time, traceback
sys.path.insert(0, "scripts")
import sources as S
import akshare as ak
def cmp(key, new, kind="rel"):
    old = S.load_cache(key)
    common = sorted(set(old) & set(new))
    if not new:
        print(f"   {key}: 空"); return
    ks = sorted(new)
    msg = f"   {key}: 新 {len(new)} 条 {ks[0]}~{ks[-1]} 最新 {new[ks[-1]]}"
    if common:
        diffs = [abs(new[d] - old[d]) if kind == "abs" else abs(new[d] / old[d] - 1) for d in common[-120:] if old[d]]
        msg += f" | 重叠 {len(common)} 天，近 120 天差异中位 {st.median(diffs):.4f} 最大 {max(diffs):.4f}（{kind}） 缓存最新 {old[max(old)]}"
    else:
        msg += f" | 无重叠，缓存最新 {max(old) if old else '-'} {old[max(old)] if old else ''}"
    print(msg)
def T(label, key, fn, kind="rel"):
    print("==", label)
    try:
        t = time.time(); d = fn(); cmp(key, d, kind); print(f"   用时 {time.time()-t:.1f}s")
    except Exception as e:
        print("   失败", type(e).__name__, str(e)[:200])
def csi_value(code, col):
    df = ak.stock_zh_index_value_csindex(symbol=code)
    print("   列", list(df.columns))
    return {str(r["日期"])[:10]: float(r[col]) for _, r in df.iterrows()}
for code, key in (("000300", "pe300"), ("000510", "pe_a500"), ("930955", "hl100_pe"), ("000688", "pe_kc")):
    for col in ("市盈率1", "市盈率2"):
        T(f"中证指数日度指标 {code} {col}", key, lambda c=code, col=col: csi_value(c, col))
T("中证官网 index-perf 科创50 peg", "pe_kc", lambda: S.cs_perf("000688", "peg", "20200101"))
for code, key in (("SH000300", "pe300"), ("CSI930955", "hl100_pe"), ("SH000510", "pe_a500")):
    T(f"蛋卷 {code}", key, lambda c=code: S.dj_pe(c))
def lg(sym):
    df = ak.stock_index_pe_lg(symbol=sym); print("   列", list(df.columns))
    return {str(r["日期"])[:10]: float(r["滚动市盈率"]) for _, r in df.iterrows()}
T("乐咕 沪深300 滚动市盈率", "pe300", lambda: lg("沪深300"))
# 创业板指市盈率：国证指数官网
def cni_pe(code):
    url = f"https://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat?indexCode={code}&startDate=2024-01-01&endDate={dt.date.today()}&frequency=day"
    j = S.jget(url, "https://www.cnindex.com.cn/"); data = j.get("data") or {}
    print("   列", data.get("item"))
    return {}
T("国证指数 399006 字段", "pe_cyb", lambda: cni_pe("399006"))
# 十年国债：中债
def chinabond():
    out = {}
    y1 = dt.date.today().year
    for y in range(y1 - 1, y1 + 1):
        df = ak.bond_china_yield(start_date=f"{y}0101", end_date=f"{y}1231" if y < y1 else dt.date.today().strftime("%Y%m%d"))
        if y == y1 - 1: print("   列", list(df.columns), df["曲线名称"].unique()[:6])
        df = df[df["曲线名称"].astype(str).str.contains("国债")]
        for _, r in df.iterrows(): out[str(r["日期"])[:10]] = float(r["10年"])
    return out
T("中债 国债收益率曲线 10 年", "cn10y", chinabond, "abs")
def zhus():
    df = ak.bond_zh_us_rate(start_date="20240101"); print("   列", list(df.columns))
    return {str(r["日期"])[:10]: float(r["中国国债收益率10年"]) for _, r in df.iterrows() if str(r["中国国债收益率10年"]) != "nan"}
T("AKShare 中美国债 中国10年", "cn10y", zhus, "abs")
# 破净率：东方财富全市场快照 f23 市净率
def pb_snap():
    import topsig
    n = below = 0
    for pn in range(1, 80):
        q = S.urllib.parse.urlencode({"pn": pn, "pz": 200, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12", "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23", "fields": "f12,f23", "ut": topsig.UT})
        rows = ((S.jget("https://push2.eastmoney.com/api/qt/clist/get?" + q, "https://quote.eastmoney.com/") or {}).get("data") or {}).get("diff") or []
        if not rows: break
        for r in rows:
            p = r.get("f23")
            if isinstance(p, (int, float)):
                n += 1; below += 0 < p < 1
    print(f"   {n} 只有市净率，破净 {below}")
    d = dt.date.today()
    return {d.isoformat(): below / n}
T("东方财富快照算破净率", "pb_below", pb_snap, "abs")
# 两市成交额：腾讯当天行情
def tx_amt():
    t = S.http("https://qt.gtimg.cn/q=sh000001,sz399001", "https://gu.qq.com/")
    tot = 0; d = None
    for line in t.strip().split(";"):
        if "~" not in line: continue
        f = line.split("~"); tot += float(f[37]) / 1e4; d = f[30][:8]
    return {f"{d[:4]}-{d[4:6]}-{d[6:]}": round(tot, 2)}
T("腾讯行情 两市成交额（当天）", "mkt_amt", tx_amt)
# 融资余额：上交所 + 深交所
def margin_ex():
    a = ak.stock_margin_sse(start_date=(dt.date.today() - dt.timedelta(days=40)).strftime("%Y%m%d"), end_date=dt.date.today().strftime("%Y%m%d"))
    print("   上交所列", list(a.columns))
    out = {}
    for _, r in a.iterrows():
        d = str(r["信用交易日期"]); d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        try:
            b = ak.stock_margin_szse(date=d.replace("-", "")); out[d] = (float(r["融资余额"]) + float(b["融资余额"].iloc[0]) * 1e8) / 1e8
        except Exception as e:
            pass
        if len(out) >= 5: break
    return out
T("交易所 融资余额", "margin", margin_ex)
# 宏观
def m1b():
    df = ak.macro_china_supply_of_money()
    return {S._month(r["统计时间"]): float(r["货币(狭义货币M1)同比增长"]) for _, r in df.iterrows() if str(r["货币(狭义货币M1)同比增长"]) not in ("nan", "")}
T("AKShare 货币供应（另一来源）M1 同比", "m1", m1b, "abs")
def loanb():
    for fn in ("macro_rmb_loan", "macro_china_rmb_loan"):
        if hasattr(ak, fn):
            df = getattr(ak, fn)(); print("  ", fn, list(df.columns)); print(df.tail(2).to_string()); return {}
    return {}
T("新增人民币贷款 另一来源", "loan", loanb)
def fred_dfii():
    import csv, io
    txt = S.http("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10&cosd=2025-06-01", timeout=120, tries=1)
    rd = csv.reader(io.StringIO(txt)); next(rd)
    return {r[0]: float(r[1]) for r in rd if len(r) > 1 and r[1] not in (".", "")}
T("FRED DFII10（近一年）", "real10", fred_dfii, "abs")
def spdr_csv():
    t = S.http("https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv", "https://www.spdrgoldshares.com/", timeout=60)
    lines = t.splitlines(); print("   表头", lines[:3])
    return {}
T("SPDR 官网 CSV", "spdr", spdr_csv)
def ag_sge():
    df = ak.spot_hist_sge(symbol="Ag(T+D)")
    return {str(r["date"])[:10]: float(r["close"]) for _, r in df.iterrows()}
T("上金所 Ag(T+D)", "ag0", ag_sge)
def ag_sina():
    df = ak.futures_zh_daily_sina(symbol="AG0"); print("   列", list(df.columns))
    return {str(r["date"])[:10]: float(r["close"]) for _, r in df.iterrows()}
T("新浪期货日线 AG0", "ag0", ag_sina)
