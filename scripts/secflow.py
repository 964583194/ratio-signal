"""行业 ETF 资金（实验，只作参考，不改任何买卖）：钱最近流到哪个板块

上交所、深交所每天的 ETF 份额里，按名字把行业 ETF 分组（半导体、机器人、航天军工、人工智能……），
每组取份额最大的几只（覆盖大部分规模），份额变化 × 当天净值 = 净申购。
相对值：净申购 ÷ 这一组 ETF 的规模（%），不同板块大小不一样也能比。
缓存 data/raw/sec_etf.json；历史从 2025-06 起，每次更新补一批（上交所慢慢抓，免得被封）。
"""
import bisect
import datetime as dt
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import sources as S
from divflow import _sse, _timed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "raw", "sec_etf.json")
OUT = os.path.join(ROOT, "data", "secflow.json")
SINCE = "2025-06-02"
PER_RUN, TOP = int(os.environ.get("SEC_PER_RUN", 40)), 5
SKIP = ("港", "恒生", "香港", "标普", "中概", "海外", "亚太", "美国", "纳斯达克", "纳指", "日经", "德国", "法国", "沙特", "东南亚",
        "债", "货币", "现金", "短融", "黄金ETF", "上海金", "豆粕", "能源化工", "有色金属期货")
GROUPS = [  # 先匹配到的算（顺序有讲究：行业在宽基前，"创业板人工智能"算人工智能；机器人在人工智能前，半导体在电子前）
    ("红利", ("红利",)),
    ("机器人", ("机器人",)),
    ("半导体芯片", ("半导体", "芯片", "集成电路", "科创芯片")),
    ("航天军工", ("军工", "国防", "航天", "航空", "卫星", "低空", "通航")),
    ("人工智能", ("人工智能", "AI", "算力", "大数据", "云计算", "数据")),
    ("通信", ("通信", "5G", "光模块", "物联网")),
    ("软件信创", ("软件", "计算机", "信创", "信息技术", "信息安全", "网络安全")),
    ("电子", ("电子", "消费电子", "智能硬件")),
    ("证券", ("证券", "券商", "非银", "金融科技")),
    ("银行", ("银行",)),
    ("保险", ("保险",)),
    ("医药医疗", ("医药", "医疗", "创新药", "生物", "中药", "疫苗", "健康")),
    ("汽车", ("汽车", "智能车", "车")),
    ("新能源", ("光伏", "新能源", "储能", "电池", "锂", "碳中和", "绿色电力", "风电")),
    ("消费", ("消费", "食品", "酒", "家电", "旅游", "饮料")),
    ("有色资源", ("有色", "稀土", "黄金股", "矿业", "金属", "资源")),
    ("煤炭钢铁化工", ("煤炭", "钢铁", "化工", "建材", "石油", "油气")),
    ("电力公用", ("电力", "电网", "公用", "核电")),
    ("地产基建", ("地产", "房地产", "基建", "建筑", "工程机械")),
    ("传媒游戏", ("传媒", "游戏", "动漫", "影视")),
    ("农业", ("农业", "养殖", "畜牧", "粮食")),
    # 宽基（国家队常买的那几类），放最后
    ("A500", ("A500",)),
    ("科创50", ("科创50", "科创板50", "科创ETF", "科创100", "科创板")),
    ("创业板", ("创业板", "创50", "创业")),
    ("沪深300", ("沪深300", "300ETF")),
    ("中证1000", ("中证1000", "1000ETF")),
    ("中证500", ("中证500", "500ETF")),
    ("上证50", ("上证50", "50ETF")),
]
BROAD = {"沪深300", "上证50", "中证500", "中证1000", "A500", "科创50", "创业板"}


def group_of(nm):
    if not nm or any(s in nm for s in SKIP):
        return None
    for g, kws in GROUPS:
        if any(k in nm for k in kws):
            return g
    return None


def fetch(Z):
    if os.environ.get("NO_FETCH"):
        return
    names, sh, nav = Z.setdefault("names", {}), Z.setdefault("shares", {}), Z.setdefault("nav", {})
    done = set(Z.setdefault("sse_days", []))
    wd = S._wdays(SINCE)
    todo = wd[-5:] + [d for d in reversed(wd[:-5]) if d not in done][:PER_RUN]
    t0, ok = time.time(), 0
    for d in todo:
        d, rows = _sse(d)
        if rows is None:
            if "403" in getattr(S, "_last_err", ""):
                print("  上交所拒绝访问（403），这次先停，下次再补")
                break
            continue
        done.add(d)
        ok += bool(rows)
        for r in rows:
            nm = r.get("SEC_NAME") or ""
            if group_of(nm) and r.get("TOT_VOL"):
                names[r["SEC_CODE"]] = nm
                sh.setdefault(r["SEC_CODE"], {})[d] = float(r["TOT_VOL"]) * 1e4
        time.sleep(0.3)
    Z["sse_days"] = sorted(done)
    print(f"  上交所：抓 {len(todo)} 天，有数 {ok} 天，{time.time() - t0:.0f}s；还差 {len([d for d in wd if d not in done])} 天")
    try:
        import akshare as ak  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        ak = None
    if ak:
        # 深交所：一次取最近半年（和国家队那只 159919 用的是同一个接口，它能取到）；接口偶尔断，多试两次
        last_sz = Z.get("szse_last", "")
        if last_sz < (dt.date.today() - dt.timedelta(days=1)).isoformat():
            d0 = max(dt.date.fromisoformat(SINCE), dt.date.today() - dt.timedelta(days=175))
            if last_sz:
                d0 = max(d0, dt.date.fromisoformat(last_sz) - dt.timedelta(days=7))
            df = None
            for k in range(3):
                df = _timed(lambda: ak.fund_scale_daily_szse(start_date=d0.strftime("%Y%m%d"), end_date=dt.date.today().strftime("%Y%m%d")), 240)
                if df is not None:
                    break
                time.sleep(5 * (k + 1))
            if df is None:
                print("  深交所：取不到，下次再补")
            else:
                col = "基金简称" if "基金简称" in df.columns else [c for c in df.columns if "简称" in c][0]
                n0 = 0
                for _, r in df[df[col].astype(str).map(lambda x: group_of(x) is not None)].iterrows():
                    c = str(r["基金代码"]).zfill(6)
                    names[c] = str(r[col])
                    sh.setdefault(c, {})[str(r["日期"])[:10]] = float(r["基金份额"])
                    n0 += 1
                Z["szse_last"] = str(df["日期"].max())[:10]
                print(f"  深交所：{d0} 起 {n0} 条，到 {Z['szse_last']}")
    # 每组份额最大的几只拿净值
    top = _tops(Z)
    last = max((max(v) for v in sh.values() if v), default="")

    def one(c):
        if nav.get(c) and max(nav[c]) >= last:
            return c, None
        try:
            return c, {d: v for d, v in S.em_pzd(c).items() if d >= "2025-05-01"}
        except Exception as e:  # noqa: BLE001
            print("  净值", c, e)
            return c, None
    with ThreadPoolExecutor(3) as ex:
        for c, v in ex.map(one, [c for cs in top.values() for c in cs]):
            if v:
                nav[c] = v


def _tops(Z):
    out = {}
    for c, nm in Z.get("names", {}).items():
        g = group_of(nm)
        s = Z["shares"].get(c) or {}
        if g and s:
            out.setdefault(g, []).append((s[max(s)], c))
    return {g: [c for _, c in sorted(v, reverse=True)[:TOP]] for g, v in out.items()}


def run():
    try:
        with open(CACHE, encoding="utf-8") as fh:
            Z = json.load(fh)
    except (OSError, ValueError):
        Z = {}
    fetch(Z)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(Z, fh, ensure_ascii=False, separators=(",", ":"))
    SH, NV = Z.get("shares", {}), Z.get("nav", {})
    top = _tops(Z)
    days = sorted({d for c in SH for d in SH[c] if d >= SINCE})
    ix = {d: i for i, d in enumerate(days)}
    n = len(days)
    G = {}
    for g, cs in top.items():
        flow, size = [0.0] * n, [0.0] * n
        for c in cs:
            ks = sorted(d for d in SH[c] if d in ix)
            nk = sorted(NV.get(c, {}))
            if len(ks) < 2 or not nk:
                continue

            def nav(d):
                j = bisect.bisect_right(nk, d) - 1
                return NV[c][nk[j]] if j >= 0 else None
            for a, b in zip(ks, ks[1:]):
                v = nav(b)
                if v:
                    flow[ix[b]] += (SH[c][b] - SH[c][a]) * v / 1e8
            j = 0
            for i, d in enumerate(days):
                while j + 1 < len(ks) and ks[j + 1] <= d:
                    j += 1
                if ks[0] <= d and (v := nav(d)):
                    size[i] += SH[c][ks[j]] * v / 1e8
        G[g] = {"flow": flow, "size": size, "etfs": [Z["names"][c] for c in cs]}
    i = n - 1
    while i > 0 and all(not G[g]["flow"][i] for g in G):
        i -= 1

    def win(g, w):
        f = sum(G[g]["flow"][max(0, i - w + 1):i + 1])
        s = G[g]["size"][i] or 1
        return round(f, 1), round(f / s * 100, 1)
    rows = []
    for g in G:
        if not G[g]["size"][i]:
            continue
        r = {"name": g, "kind": "宽基" if g in BROAD else "红利" if g == "红利" else "行业", "size": round(G[g]["size"][i]), "etfs": G[g]["etfs"]}
        for w, k in ((5, "w1"), (20, "w4"), (60, "w13")):
            r[k], r[k + "p"] = win(g, w)
        rows.append(r)
    rows.sort(key=lambda r: -r["w4p"])
    cover = len([d for d in days if d in set(Z.get("sse_days", []))]) / max(1, len(S._wdays(SINCE)))
    data = {"updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
            "date": days[i] if days else None, "rows": rows, "cover": round(cover, 2), "since": SINCE}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    top3 = "、".join(f"{r['name']} {r['w4p']:+.1f}%" for r in rows[:3])
    print(f"写入 {OUT}：{data['date']} {len(rows)} 个板块；近 4 周流入最多（占规模）：{top3}；历史补齐 {cover:.0%}")
    return data


if __name__ == "__main__":
    run()
