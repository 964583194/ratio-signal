"""红利 ETF 资金（实验，只作参考，不改红利买卖）

A 股红利类 ETF（名字带"红利"，不含港股 / 恒生 / 标普等海外）每天的份额 × 当天净值 → 每天净申购（亿元）。
回看 2023 年起：越跌越买、越涨越卖（2026-06 红利见底、科创见顶时净流入 +143 亿，7~8 月反弹时流出）。
所以不当买点，只当"红利在跌、有人在接 / 红利在涨、资金在卖"的佐证。
缓存 data/raw/div_etf.json；历史没补齐的日子每次更新补一批（上交所按天、深交所按月）。
"""
import bisect
import datetime as dt
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "raw", "div_etf.json")
OUT = os.path.join(ROOT, "data", "divflow.json")
SINCE = "2023-01-03"
BAD = ("港", "恒生", "香港", "标普", "中概", "海外", "亚太", "美国", "沪港深", "港股通")
SSE_PER_RUN, SZSE_PER_RUN = 250, 12


def _a_share(nm):
    return "红利" in nm and not any(b in nm for b in BAD)


def _sse(d):
    u = ("https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback1&isPagination=true&pageHelp.pageSize=10000"
         "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
         f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}&_={int(time.time() * 1000)}")
    try:
        t = S.http(u, "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/")
        j = json.loads(t[t.index("(") + 1:t.rindex(")")])
        return d, (j.get("pageHelp") or {}).get("data") or j.get("result") or []
    except Exception as e:  # noqa: BLE001
        print("  上交所", d, e)
        return d, None


def fetch(Z):
    if os.environ.get("NO_FETCH"):
        return
    names, sh, nav = Z.setdefault("names", {}), Z.setdefault("shares", {}), Z.setdefault("nav", {})
    done = set(Z.setdefault("sse_days", []))
    wd = S._wdays(SINCE)
    recent = wd[-5:]                                   # 最近几天每次都重抓（当天可能还没发布）
    todo = recent + [d for d in reversed(wd[:-5]) if d not in done][:SSE_PER_RUN]
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(_sse, todo))
    ok = 0
    for d, rows in res:
        if not rows:
            continue
        ok += 1
        done.add(d)
        for r in rows:
            nm = r.get("SEC_NAME") or ""
            if _a_share(nm) and r.get("TOT_VOL"):
                names[r["SEC_CODE"]] = nm
                sh.setdefault(r["SEC_CODE"], {})[d] = float(r["TOT_VOL"]) * 1e4
    Z["sse_days"] = sorted(done)
    print(f"  上交所：抓 {len(todo)} 天，成功 {ok}，{time.time() - t0:.0f}s；还差 {len([d for d in wd if d not in done])} 天")
    try:
        import akshare as ak  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        ak = None
    if ak:
        mdone = set(Z.setdefault("szse_months", []))
        months = sorted({d[:7] for d in wd})
        todo = months[-2:] + [m for m in reversed(months[:-2]) if m not in mdone][:SZSE_PER_RUN]
        for m in todo:
            a = dt.date.fromisoformat(m + "-01")
            b = min(dt.date.today(), (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
            try:
                df = ak.fund_scale_daily_szse(start_date=a.strftime("%Y%m%d"), end_date=b.strftime("%Y%m%d"))
                col = "基金简称" if "基金简称" in df.columns else [c for c in df.columns if "简称" in c][0]
                x = df[df[col].astype(str).map(_a_share)]
                for _, r in x.iterrows():
                    c = str(r["基金代码"]).zfill(6)
                    names[c] = str(r[col])
                    sh.setdefault(c, {})[str(r["日期"])[:10]] = float(r["基金份额"])
                mdone.add(m)
            except Exception as e:  # noqa: BLE001
                print("  深交所", m, e)
        Z["szse_months"] = sorted(mdone)
    last = max((max(v) for v in sh.values() if v), default="")

    def one(c):
        if nav.get(c) and max(nav[c]) >= last:
            return c, None
        try:
            return c, {d: v for d, v in S.em_pzd(c).items() if d >= "2022-12-01"}
        except Exception as e:  # noqa: BLE001
            print("  净值", c, e)
            return c, None
    with ThreadPoolExecutor(6) as ex:
        for c, v in ex.map(one, list(names)):
            if v:
                nav[c] = v


def run():
    try:
        with open(CACHE, encoding="utf-8") as fh:
            Z = json.load(fh)
    except (OSError, ValueError):
        Z = {}
    fetch(Z)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(Z, fh, ensure_ascii=False, separators=(",", ":"))
    names = {c: n for c, n in Z.get("names", {}).items() if _a_share(n)}
    SH, NV = Z.get("shares", {}), Z.get("nav", {})
    H = S.load_cache("hl100")
    dates = sorted(d for d in H if d >= SINCE)
    ix = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    flow, size = [0.0] * n, [0.0] * n
    for c in names:
        ks = sorted(d for d in SH.get(c, {}) if d in ix)
        nk = sorted(NV.get(c, {}))
        if not ks or not nk:
            continue

        def nav(d):
            j = bisect.bisect_right(nk, d) - 1
            return NV[c][nk[j]] if j >= 0 else None
        for a, b in zip(ks, ks[1:]):
            v = nav(b)
            if v:
                flow[ix[b]] += (SH[c][b] - SH[c][a]) * v / 1e8
        # 规模：两次有数之间按上一次的份额 × 当天净值
        j = 0
        for i, d in enumerate(dates):
            while j + 1 < len(ks) and ks[j + 1] <= d:
                j += 1
            if ks[0] <= d:
                v = nav(d)
                if v:
                    size[i] += SH[c][ks[j]] * v / 1e8
    hl = [H[d] for d in dates]
    i = n - 1
    while i > 0 and not flow[i] and not flow[i - 1]:
        i -= 1                                           # 最后一两天份额还没发布
    f20 = sum(flow[max(0, i - 19):i + 1])
    h20 = (hl[i] / hl[max(0, i - 20)] - 1) * 100
    pct = f20 / size[i] * 100 if size[i] else 0
    if h20 <= -3 and f20 > 0:
        tag, txt = "有人在接", "红利在跌，资金在流入：底部有人接（历史上流入时红利常还在跌，不是买点）"
    elif h20 >= 3 and f20 < 0:
        tag, txt = "涨了在卖", "红利在涨，资金在流出：涨了有人卖，不追"
    elif pct >= 3:
        tag, txt = "流入", "资金在流入"
    elif pct <= -3:
        tag, txt = "流出", "资金在流出，红利暂时没人追"
    else:
        tag, txt = "平稳", "资金进出不大"
    def last_size(c):
        s, v = SH.get(c) or {}, NV.get(c) or {}
        return s[max(s)] * v[max(v)] / 1e8 if s and v else 0
    big = sorted(names, key=last_size, reverse=True)[:8]
    cover = len([d for d in dates if d in set(Z.get("sse_days", []))]) / max(1, n)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "dates": dates, "hl": hl, "flow": [round(x, 2) for x in flow], "size": [round(x, 1) for x in size],
        "latest": {"date": dates[i], "f20": round(f20), "pct20": round(pct, 1), "h20": round(h20, 1), "size": round(size[i]),
                   "n": len(names), "tag": tag, "text": txt, "cover": round(cover, 2),
                   "top": [{"code": c, "name": names[c], "size": round(last_size(c))} for c in big]},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{dates[i]} {len(names)} 只，规模 {size[i]:.0f} 亿，近 20 日 {f20:+.0f} 亿（{pct:+.1f}%），红利 {h20:+.1f}% → {tag}；历史补齐 {cover:.0%}")
    return data


if __name__ == "__main__":
    run()
