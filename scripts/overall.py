"""大方向 + 宽基加大 / 暂停（实验，只作提醒，不改倍数）+ 国家队 vs 红利资金（总览图）

一、大方向（总览最上面一句话，只作总结，不直接决定买多少）
  市场温度（底部/偏冷 +1，偏热/顶部 −1）、宽基估值（便宜指数 ≥60 +1，<40 −1）、方向（宽度/M1/信贷 ≥2 个回升 +1，0 个 −1）、
  国家队（低位集中买 +1，卖出/高位护盘 −1）、资金切换（红利流出 + 国家队买大盘 +1，红利流入 + 国家队在卖 −1），加起来：
  ≥+3 进攻，≤−2 防守，其余照常。2023 起 +3 以上之后 250 天都涨，−4 以下之后 60 天都跌；但简单加总拿来操作，去掉国家队那两项赢不了随机，
  所以只当总结，具体怎么做看各板块自己的规则。
二、宽基加大 / 暂停（2023 起用宽基真实规则回测：现行 4.61% → 6.23%，2024 起 4.85% → 7.19%、回撤 −20% → −18.5%）
  快速加大：国家队在低位集中买 + 至少 1 个（便宜指数 ≥60、见底灯 ≥4、国家队一波比一波多）→ 之后 10 个交易日每天多买 0.4 周的量；3 个以上翻倍（0.8 周）
  慢慢加：便宜指数 ≥60 + 见底灯 ≥4，但国家队没在买 → 之后 4 个周五各多买 1 周（常常还要跌一段，所以慢）
  暂停：国家队在卖 / 高位护盘、见顶灯 ≥2、便宜指数 <40，同时 2 个以上 → 宽基这周不买，钱留在红利池
  一段行情只加一次；现行"集中大买额外 4 周"照旧。
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "overall.json")


def _load(n):
    try:
        with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _week(d):
    x = dt.date.fromisoformat(d)
    return (x - dt.timedelta(days=x.weekday())).isoformat()


def run():
    T = _load("temp.json")
    t = T["series"][-1]                     # [日期, 区间 0~4, 沪深300, 见底灯, 见顶灯, 各灯, 方向]
    zone, bot, top, nup = t[1], t[3], t[4], t[6].count("1")
    HS = (_load("hs300.json") or {}).get("latest") or {}
    cheap = HS.get("cheap") or 50
    Z = (_load("ntfstage.json") or {}).get("latest") or {}
    nk = Z.get("key", "none")
    nt_buy = nk in ("buy_first", "buy_up", "buy_slow")
    nt_bad = nk.startswith("sell") or nk == "hi_buy"
    DF = (_load("divflow.json") or {}).get("latest") or {}
    f20 = DF.get("pct20") or 0
    zn = ["底部", "偏冷", "正常", "偏热", "顶部"][zone]
    items = [
        ("市场温度", 1 if zone <= 1 else -1 if zone >= 3 else 0, f"{zn}（见底灯 {bot}，见顶灯 {top}）"),
        ("宽基估值", 1 if cheap >= 60 else -1 if cheap < 40 else 0, f"便宜指数 {cheap:.0f}"),
        ("方向", 1 if nup >= 2 else -1 if nup == 0 else 0, f"宽度、M1、信贷 {nup} / 3 回升"),
        ("国家队", 1 if nt_buy else -1 if nt_bad else 0, Z.get("name") or "没有集中买卖"),
        ("资金切换", 1 if (f20 <= -2 and nt_buy) else -1 if (f20 >= 2 and nt_bad) else 0,
         f"红利 ETF 近 20 天 {f20:+.1f}%（占规模）" + ("，国家队在买大盘" if nt_buy else "，国家队在卖" if nt_bad else "")),
    ]
    sc = sum(v for _, v, _ in items)
    direction = "进攻" if sc >= 3 else "防守" if sc <= -2 else "照常"
    dcls = {"进攻": "g2", "防守": "r1", "照常": "c0"}[direction]
    dtext = {"进攻": "整体偏多：规则让加码时别犹豫", "防守": "整体偏空：不追加，到卖出线就卖", "照常": "没有明显方向：全部照规则"}[direction]

    # 宽基加大 / 暂停
    ups = [("便宜指数 ≥60", cheap >= 60), ("见底灯 ≥4", bot >= 4), ("国家队低位集中买", nt_buy), ("国家队一波比一波多", nk == "buy_up")]
    dns = [("国家队在卖 / 高位护盘", nt_bad), ("见顶灯 ≥2", top >= 2), ("便宜指数 <40", cheap < 40)]
    nu, nd = sum(1 for _, v in ups if v), sum(1 for _, v in dns if v)
    if nd >= 2:
        kact, kkey, klv = "暂停：宽基这周不买，钱留在红利池，灯灭了再恢复", "暂停", "重点"
    elif nt_buy and nu >= 3:
        kact, kkey, klv = "⚠ 快速加大（翻倍）：之后 10 个交易日，每天多买宽基周额的 0.8 倍（合计 8 周），备用金可以用", "快速加大（翻倍）", "重点"
    elif nt_buy and nu >= 2:
        kact, kkey, klv = "⚠ 快速加大：之后 10 个交易日，每天多买宽基周额的 0.4 倍（合计 4 周）", "快速加大", "重点"
    elif cheap >= 60 and bot >= 4:
        kact, kkey, klv = "慢慢加：之后 4 个周五，每次多买 1 周的量（国家队没在买，常常还要跌一段）", "慢慢加", "普通"
    else:
        left = [n for n, v in ups if not v]
        kact, kkey, klv = "照常：按便宜指数倍数每周五买" + ("（国家队在买，再亮 1 个灯就快速加大）" if nt_buy and nu == 1 else ""), "照常", None
    # 国家队 vs 红利 资金：近一年按周加总（亿元）
    N = _load("ntf.json") or {}
    G = N.get("gflow") or {}
    S = N.get("series") or []
    nt_w, hs_w = {}, {}
    if G:
        L = len(G["v"][G["names"][0]])
        SS = S[-L:]
        for k in range(L):
            w = _week(SS[k][0])
            nt_w[w] = nt_w.get(w, 0) + sum(G["v"][g][k] or 0 for g in G["names"])
            hs_w[w] = SS[k][4]
    F = _load("divflow.json") or {}
    dv_w, hl_w = {}, {}
    for d, v, h in zip(F.get("dates", []), F.get("flow", []), F.get("hl", [])):
        w = _week(d)
        dv_w[w] = dv_w.get(w, 0) + v
        hl_w[w] = h
    weeks = sorted(w for w in nt_w if w >= (dt.date.fromisoformat(max(nt_w)) - dt.timedelta(days=365)).isoformat()) if nt_w else []
    flows = {"weeks": weeks, "nt": [round(nt_w[w]) for w in weeks], "div": [round(dv_w.get(w, 0), 1) for w in weeks],
             "hs": [hs_w[w] for w in weeks], "hl": [hl_w.get(w) for w in weeks]}
    n4 = sum(flows["nt"][-4:]) if weeks else 0
    d4 = sum(flows["div"][-4:]) if weeks else 0
    ftext = (f"近 4 周：国家队 {n4:+,.0f} 亿，红利 ETF {d4:+,.0f} 亿 → "
             + ("钱在从红利换到大盘（国家队在托）" if n4 > 0 and d4 < 0 else "钱在从大盘躲进红利（避险）" if n4 < 0 and d4 > 0
                else "两边都在流入" if n4 > 0 and d4 > 0 else "两边都在流出" if n4 < 0 and d4 < 0 else "进出不大"))
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"), "date": t[0],
        "dir": direction, "dcls": dcls, "dtext": dtext, "score": sc,
        "items": [{"name": a, "v": b, "text": c} for a, b, c in items],
        "kuanji": {"key": kkey, "act": kact, "level": klv, "ups": [{"name": a, "on": b} for a, b in ups], "downs": [{"name": a, "on": b} for a, b in dns]},
        "flows": flows, "ftext": ftext,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{t[0]} 大方向 {direction}（{sc:+d}）；宽基 {kkey}（加码灯 {nu}/4，减速灯 {nd}/3）；{ftext}")
    return data


if __name__ == "__main__":
    run()
