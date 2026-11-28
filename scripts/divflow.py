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
SSE_PER_RUN, SZSE_PER_RUN = 60, 12   # 上交所抓太快会被封（403），连带国家队那几只 ETF 也取不到：每次少抓一点、慢一点


def _a_share(nm):
    return "红利" in nm and not any(b in nm for b in BAD)


def _sse_ak(d):
    """备用：AKShare 的上交所 ETF 规模（列名不固定，按含义找）；份额统一成"万份"，和主接口一样"""
    import akshare as ak  # noqa: PLC0415
    df = _timed(lambda: ak.fund_etf_scale_sse(date=d.replace("-", "")), 60)
    if df is None or not len(df):
        return []
    col = lambda *ks: next(c for c in df.columns if any(k in str(c) for k in ks))  # noqa: E731
    cc, cn, cv = col("代码"), col("简称", "名称"), col("份额")
    vals = df[cv].astype(float)
    scale = 1e-4 if vals.median() > 1e6 else 1.0          # 份 → 万份
    return [{"SEC_CODE": str(r[cc]).zfill(6), "SEC_NAME": str(r[cn]), "TOT_VOL": float(r[cv]) * scale} for _, r in df.iterrows()]


def _sse(d):
    """上交所某天全部 ETF 的份额：先用上交所接口，不行再用 AKShare 备用"""
    if not os.environ.get("FORCE_BACKUP"):
        r = _sse_main(d)
        if r[1] is not None:
            return r
    try:
        rows = _sse_ak(d)
        print("  上交所备用（AKShare）", d, len(rows), "只")
        return d, rows
    except Exception as e:  # noqa: BLE001
        print("  上交所备用也失败", d, e)
        return d, None


def szse_now():
    """备用：深交所 ETF 列表里的"当前规模(份)"（只有上一个交易日一天），{代码: (简称, 份额)}"""
    import io as _io  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    b = S.http("https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1945&TABKEY=tab1", "https://www.szse.cn/", raw=True)
    df = pd.read_excel(_io.BytesIO(b), dtype={"证券代码": str})
    d = dt.date.today() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat(), {str(r["证券代码"]).zfill(6): (str(r["证券简称"]), float(str(r["当前规模(份)"]).replace(",", ""))) for _, r in df.iterrows()}


def nav_hist(code, since, have=False):
    """单位净值：天天基金 → 东方财富 → 新浪，哪个能用用哪个"""
    for nm, fn in (("天天基金", lambda: S.em_pzd(code)), ("东方财富", lambda: S.em_lsjz(code, 3 if have else 40)), ("新浪", lambda: S.sina_nav(code, 30 if have else 600))):
        if os.environ.get("FORCE_BACKUP") and nm == "天天基金":
            continue
        try:
            v = {d: x for d, x in fn().items() if d >= since}
            if v:
                return v
        except Exception:  # noqa: BLE001
            pass
    raise RuntimeError("净值三个接口都失败")


def _sse_main(d):
    u = ("https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback1&isPagination=true&pageHelp.pageSize=10000"
         "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
         f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}&_={int(time.time() * 1000)}")
    try:
        t = S.http(u, "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/")
        j = json.loads(t[t.index("(") + 1:t.rindex(")")])
        return d, (j.get("pageHelp") or {}).get("data") or j.get("result") or []
    except Exception as e:  # noqa: BLE001
        S._last_err = str(e)
        print("  上交所", d, e)
        return d, None


def _timed(fn, sec):
    """在后台线程里跑，超过 sec 秒就放弃（接口偶尔卡住不返回，会拖住整个更新）"""
    import threading  # noqa: PLC0415
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    th.start()
    th.join(sec)
    return box.get("v")


def _szse_backup(Z, keep):
    """深交所备用：AKShare 没取到最近一天时，用深交所列表的"当前规模"补上（只有一天，但够每天往前走）"""
    names, sh = Z.setdefault("names", {}), Z.setdefault("shares", {})
    sz = [c for c in names if c.startswith("1")]
    last = max((max(sh[c]) for c in sz if sh.get(c)), default="")
    try:
        d, rows = szse_now()
    except Exception as e:  # noqa: BLE001
        print("  深交所备用失败", e)
        return
    if last >= d and not os.environ.get("FORCE_BACKUP"):
        return
    n = 0
    for c, (nm, v) in rows.items():
        if keep(nm):
            names[c] = nm
            sh.setdefault(c, {})[d] = v
            n += 1
    print(f"  深交所备用（当前规模）{d} {n} 只")


def fetch(Z):
    if os.environ.get("NO_FETCH"):
        return
    names, sh, nav = Z.setdefault("names", {}), Z.setdefault("shares", {}), Z.setdefault("nav", {})
    done = set(Z.setdefault("sse_days", []))
    wd = S._wdays(SINCE)
    recent = wd[-5:]                                   # 最近几天每次都重抓（当天可能还没发布）
    todo = recent + [d for d in reversed(wd[:-5]) if d not in done][:SSE_PER_RUN]
    t0 = time.time()
    res = []
    for d in todo:                                     # 一个一个抓，中间停一下；遇到 403 就停，下次再补
        r = _sse(d)
        res.append(r)
        if r[1] is None and getattr(S, "_last_err", "") and "403" in S._last_err:
            print("  上交所拒绝访问（403），这次先停，下次再补")
            break
        time.sleep(0.3)
    ok = 0
    for d, rows in res:
        if rows is None:
            continue
        done.add(d)                                    # 返回空的是节假日，也算抓过了，下次不再抓
        if not rows:
            continue
        ok += 1
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
                df = _timed(lambda: ak.fund_scale_daily_szse(start_date=a.strftime("%Y%m%d"), end_date=b.strftime("%Y%m%d")), 90)
                if df is None:
                    print("  深交所", m, "超时，下次再补")
                    break
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
    _szse_backup(Z, _a_share)
    last = max((max(v) for v in sh.values() if v), default="")

    def one(c):
        if nav.get(c) and max(nav[c]) >= last:
            return c, None
        try:
            return c, nav_hist(c, "2022-12-01", bool(nav.get(c)))
        except Exception as e:  # noqa: BLE001
            print("  净值", c, e)
            return c, None
    with ThreadPoolExecutor(3) as ex:
        for c, v in ex.map(one, list(names)):
            if v:
                nav[c] = {**nav.get(c, {}), **v}


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
