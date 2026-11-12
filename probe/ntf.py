"""国家队宽基 ETF：份额（上交所按日分片 / 深交所按半年）、单位净值、成交额、指数"""
import sys, json, datetime as dt, time, urllib.parse
sys.path.insert(0, "scripts")
import sources as S
SSE = ["510300","510310","510330","510050","510180","510500","512500","512100","588000","588080","512050","563360","560610","563800","512020","510100"]
SZ = ["159919","159915","159949","159922","159845","159901","159338","159352","159361","159352"]
mode, k, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
out = {}
def dump(tag):
    s = json.dumps(out, separators=(",", ":"))
    for i in range(0, len(s), 1500):
        print(f"CHUNK{tag}{i // 1500:05d}:" + s[i:i + 1500])
    print("CHUNKEND")
if mode == "sse":
    days = [d for d in S._wdays("2023-01-01")]
    days = days[k::n]
    names = {}
    for j, d in enumerate(days):
        for t in range(3):
            try:
                u = ("https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback1&isPagination=true&pageHelp.pageSize=10000"
                     "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
                     f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}&_={int(time.time() * 1000)}")
                tx = S.http(u, "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/")
                tx = tx[tx.index("(") + 1:tx.rindex(")")]
                rows = (json.loads(tx).get("pageHelp") or {}).get("data") or []
                got = {r["SEC_CODE"]: float(r["TOT_VOL"]) * 1e4 for r in rows if r.get("TOT_VOL") and r["SEC_CODE"] in SSE}
                for r in rows:
                    if r["SEC_CODE"] in SSE: names[r["SEC_CODE"]] = r.get("SEC_NAME")
                if got: out[d] = got
                break
            except Exception as e:
                time.sleep(2)
        if j % 100 == 0: print("进度", j, len(days), d, len(out), flush=True)
    out["_names"] = names
    dump("S%d" % k)
else:
    import akshare as ak
    # 深交所：每半年一次，所有基金
    szs = {}; names = {}
    d0 = dt.date(2023, 1, 1)
    while d0 <= dt.date.today():
        d1 = min(dt.date.today(), d0 + dt.timedelta(days=170))
        for t in range(4):
            try:
                df = ak.fund_scale_daily_szse(start_date=d0.strftime("%Y%m%d"), end_date=d1.strftime("%Y%m%d"))
                x = df[df["基金代码"].astype(str).isin(SZ)]
                cols = list(df.columns)
                for _, r in x.iterrows():
                    c = str(r["基金代码"]); names[c] = r.get("基金简称")
                    dd = str(r[cols[0]])[:10] if "日期" in cols[0] else str(r.get("日期") or r.get("统计日期"))[:10]
                    szs.setdefault(c, {})[dd] = float(r["基金份额"]) if "基金份额" in cols else float(r[cols[-1]])
                print("深交所", d0, d1, len(x), cols[:6], flush=True)
                break
            except Exception as e:
                print("深交所失败", d0, e, flush=True); time.sleep(6 * (t + 1))
        d0 = d1 + dt.timedelta(days=1)
    out["sz_shares"] = szs; out["sz_names"] = names
    nav, amt = {}, {}
    for c in SSE + SZ:
        try: nav[c] = S.em_pzd(c)
        except Exception as e: print("净值失败", c, e)
        sec = ("1." if c.startswith(("5", "6")) else "0.") + c
        q = urllib.parse.urlencode({"secid": sec, "fields1": "f1", "fields2": "f51,f57", "klt": "101", "fqt": "0", "beg": "20230101", "end": "20500101", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
        try:
            j = S.jget("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + q, "https://quote.eastmoney.com/")
            amt[c] = {a.split(",")[0]: float(a.split(",")[1]) for a in (j.get("data") or {}).get("klines") or []}
        except Exception as e: print("成交额失败", c, e)
        print(c, len(nav.get(c, {})), len(amt.get(c, {})), flush=True)
    out["nav"] = nav; out["amt"] = amt
    idx = {}
    for nm, sec in (("上证指数", "1.000001"), ("上证50", "1.000016"), ("中证500", "1.000905"), ("中证1000", "1.000852"), ("科创50", "1.000688"), ("创业板指", "0.399006"), ("沪深300", "1.000300")):
        try: idx[nm] = S.em_kline(sec, "20220101")
        except Exception as e: print("指数失败", nm, e)
    out["idx"] = idx
    dump("O")
