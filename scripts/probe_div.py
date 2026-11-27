"""一次性：抓 2023 年起所有名字带"红利"的 ETF 每天份额 + 单位净值 → data/raw/div_etf.json（探查用）"""
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "raw", "div_etf.json")
names, sh, nav = {}, {}, {}
days = S._wdays("2023-01-03")
t0 = time.time()
for i, d in enumerate(days):
    u = ("https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback1&isPagination=true&pageHelp.pageSize=10000"
         "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
         f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}&_={int(time.time() * 1000)}")
    try:
        t = S.http(u, "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/")
        t = t[t.index("(") + 1:t.rindex(")")]
        j = json.loads(t)
        rows = (j.get("pageHelp") or {}).get("data") or j.get("result") or []
    except Exception as e:  # noqa: BLE001
        print("sse", d, e)
        continue
    if i == 0 and rows:
        print("SSE 字段：", list(rows[0]))
    for r in rows:
        nm = r.get("SEC_NAME") or r.get("SEC_NAME_CN") or ""
        if "红利" in nm and r.get("TOT_VOL"):
            names[r["SEC_CODE"]] = nm
            sh.setdefault(r["SEC_CODE"], {})[d] = float(r["TOT_VOL"]) * 1e4
    if i % 100 == 0:
        print(d, len(names), f"{time.time() - t0:.0f}s", flush=True)
try:
    import akshare as ak  # noqa: PLC0415
    m = dt.date(2023, 1, 1)
    while m <= dt.date.today():
        e = min(dt.date.today(), (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        try:
            df = ak.fund_scale_daily_szse(start_date=m.strftime("%Y%m%d"), end_date=e.strftime("%Y%m%d"))
            col = "基金简称" if "基金简称" in df.columns else [c for c in df.columns if "简称" in c][0]
            x = df[df[col].astype(str).str.contains("红利")]
            for _, r in x.iterrows():
                c = str(r["基金代码"])
                names[c] = str(r[col])
                sh.setdefault(c, {})[str(r["日期"])[:10]] = float(r["基金份额"])
        except Exception as ex:  # noqa: BLE001
            print("szse", m, ex)
        m = e + dt.timedelta(days=1)
except Exception as ex:  # noqa: BLE001
    print("akshare", ex)
for c in names:
    try:
        nav[c] = {d: v for d, v in S.em_pzd(c).items() if d >= "2023-01-01"}
    except Exception as ex:  # noqa: BLE001
        print("nav", c, ex)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"names": names, "shares": sh, "nav": nav}, fh, ensure_ascii=False, separators=(",", ":"))
print("完成", len(names), "只", {c: n for c, n in names.items()})
