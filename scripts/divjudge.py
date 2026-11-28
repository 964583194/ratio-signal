"""红利综合判断（实验，只作提醒，不改倍数）：便宜灯 + 红利 ETF 资金 + 国家队 → 一句话怎么做

便宜灯 6 个（2018-05 起回测，红利低波100 全收益）：
  评分 ≥12（执行评分）· 红利位置 ≥60% · 估值不贵（PE 分位 <50%）· 利差 ≥3 · 技术超卖（RSI <40）· 风格偏弱（红利÷创业板 <30% 分位）
  亮 3 个：之后一年 +13.1%、98% 上涨，一年内最多再跌平均 4.7%、最坏 10.5%
  亮 4 个以上：+15.0%、100% 上涨，最多再跌平均 2.9%、最坏 8.3%
  0~2 个：一年 +7% 左右，四分之一以上的时候之后还会再跌 10% 以上（最坏 21%）
  前后两段（2018~2022-07、2022-07 起）都成立；但拿来升档调倍数赢不了随机，所以只作判断。
资金情况（2023 起，样本少）：
  突发大额流入（当天 ≥ 规模 0.8%）+ 国家队在买：3 段 2 段之后涨（2026-10-23 那次）→ ⚠ 及时看
  突发大额流入，国家队没在买：涨跌各半 → 别追
  近 20 天大额流入 ≥5 天（一直在追）：之后偏弱 → 别追
  资金流出多 + 位置便宜：之后 60 天 +2.4% → 没人要，照评分买
  国家队在卖 + 资金流出：之后 60 天 −3.6%、5% 上涨 → 偏弱，别额外加钱
跌透转头（右侧）：近 20 天评分到过 14 + 位置 ≥60% + 站上 20 日线 + 比 20 天低点高 3%：2018 起 5 次，之后 120 天全涨（+6%~+18%）→ ⚠
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "divjudge.json")


def _load(n):
    try:
        with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def run():
    V = _load("dividend.json")
    L = V["latest"]
    pos = (L.get("pos") or {}).get("value")
    lights = [
        ("评分 ≥12", L["eff"] >= 12, f"执行评分 {L['eff']:.2f}"),
        ("位置便宜", pos is not None and pos >= 0.6, f"红利位置 {round((pos or 0) * 100)}%（≥60%）"),
        ("估值不贵", L["pe_dear"] < 0.5, f"市盈率 {L['pe']:.2f}，比历史 {round(L['pe_dear'] * 100)}% 的时候贵（<50%）"),
        ("利差高", L["spread"] >= 3, f"股债利差 {L['spread']:.2f}（≥3）"),
        ("技术超卖", L["rsi"] < 40, f"RSI {L['rsi']:.0f}（<40）"),
        ("风格偏弱", L["sty_pct"] < 0.3, f"红利÷创业板 {round(L['sty_pct'] * 100)}% 分位（<30%）"),
    ]
    n = sum(1 for x in lights if x[1])
    if n >= 4:
        lv, cls, txt = "很便宜", "g2", "⚠ 红利整体很便宜：规则让买时坚定买、加码别犹豫。回测一年后都涨，一年内最多再跌约 8%"
    elif n == 3:
        lv, cls, txt = "便宜", "g2", "红利整体便宜：放心按规则买，规则让加码时坚定加码。回测一年后 98% 上涨，一年内最多再跌约 10%"
    elif n == 2:
        lv, cls, txt = "中等", "g1", "中等：照评分买，别额外加钱，之后还可能再跌 10%~20%"
    else:
        lv, cls, txt = "不便宜", "c0", "不便宜：照评分买，别额外加钱，之后还可能再跌 20%"

    # 跌透转头（右侧）：用评分走势里的执行评分和价格
    S = V["series"][-30:]
    px, ef = [x[2] for x in S], [x[3] for x in S]
    right = len(px) >= 21 and max(ef[-20:]) >= 14 and (pos or 0) >= 0.6 and px[-1] > sum(px[-20:]) / 20 and px[-1] / min(px[-20:]) - 1 >= 0.03

    # 资金
    F = _load("divflow.json")
    Z = _load("ntfstage.json")
    nk = (Z or {}).get("latest", {}).get("key", "")
    nt_buy, nt_sell = nk.startswith(("buy", "hi_buy")), nk.startswith("sell")
    flow = None
    if F and F.get("dates"):
        fl, sz = F["flow"], F["size"]
        i = len(fl) - 1
        while i > 0 and not fl[i] and not fl[i - 1]:
            i -= 1
        x = [fl[k] / sz[k] * 100 if sz[k] else 0 for k in range(len(fl))]
        f20 = sum(x[max(0, i - 19):i + 1])
        burst = max(x[max(0, i - 2):i + 1])            # 近 3 天单日最大流入
        dump = min(x[max(0, i - 4):i + 1])             # 近 5 天单日最大流出（流出"注意几天"：5 天内都算，免得隔天进进出出）
        bigd = sum(1 for v in x[max(0, i - 19):i + 1] if v >= 0.3)
        # 每天国家队是不是在买（ntfstage 的每日场景），用来找这一段"突发大额 + 国家队"从哪天开始
        ZD = (Z or {}).get("days") or {}
        zk = ZD.get("keys") or []
        zday = {}
        if ZD:
            NS = (_load("ntf.json") or {}).get("series") or []
            nd = [r[0] for r in NS]
            if ZD.get("from") in nd:
                d0 = nd.index(ZD["from"])
                zday = {nd[d0 + k]: zk[v] for k, v in enumerate(ZD["v"]) if d0 + k < len(nd)}

        def cond(k):
            return max(x[max(0, k - 2):k + 1]) >= 0.8 and zday.get(F["dates"][k], nk if k == i else "").startswith(("buy", "hi_buy"))
        ups, top = [], 0
        if burst >= 0.8 and nt_buy:
            a = i
            while a > 0 and cond(a - 1):
                a -= 1
            for k in range(max(0, a - 2), i + 1):     # 这一段里每次单日流入创新高，算一次"一笔比一笔大"
                if x[k] >= 0.8 and x[k] > top:
                    top = x[k]
                    ups.append((F["dates"][k], round(x[k], 2)))
        if burst >= 0.8 and nt_buy:
            fk, fl_lv = "burst_nt", "重点"
            if len(ups) > 1 and ups[-1][0] >= F["dates"][max(0, i - 2)]:
                ft = f"⚠ 又一笔更大的流入（{ups[-1][0][5:]} 单日 {ups[-1][1]}%，之前最大 {ups[-2][1]}%）+ 国家队在买：一笔比一笔大，着重留意，照评分买，评分到加码时别犹豫"
            else:
                ft = "⚠ 突发大额流入 + 国家队在买（像 2026-10-23）：及时看，照评分买，评分到加码时别犹豫"
        elif nt_sell and f20 >= 2:
            # 红利一直在流入 + 国家队一直在卖沪深300：资金从大盘躲进红利（2023 起之后 60 天沪深300 −4.6%、13% 上涨，红利 −1.3%；2026-04~06 就是这样）
            fk, fl_lv = "hide", "重点"
            ft = f"⚠ 红利一直在流入（近 20 天 +{f20:.1f}%）+ 国家队一直在卖沪深300：资金从大盘躲进红利，大盘偏弱，宽基别额外加钱，红利也别追（照评分买）"
        elif burst >= 0.8:
            fk, ft, fl_lv = "burst", "有人突击大额买入，别追，看后面是不是持续", None
        elif dump <= -0.8:
            # 大额流出（单日 ≤ 规模 −0.8%）：这一段（相隔 ≤10 天算同一段）里每次单日流出创新高 = 一笔比一笔大
            a, k = i, i
            while k > 0 and k > i - 60:
                k -= 1
                if x[k] <= -0.8:
                    a = k
                elif a - k > 10:
                    break
            low = 0
            for k in range(a, i + 1):
                if x[k] <= -0.8 and x[k] < low:
                    low = x[k]
                    ups.append((F["dates"][k], round(x[k], 2)))
            more = f"（又一笔更大的：{ups[-1][0][5:]} 单日 {ups[-1][1]}%，之前最大 {ups[-2][1]}%）" if len(ups) > 1 and ups[-1][0] >= F["dates"][max(0, i - 4)] else ""
            if nk.startswith(("buy_first", "buy_up", "buy_slow")):
                # 红利大额流出 + 国家队在低位 / 中间集中买沪深300：钱在从红利换到大盘（2024-02、2025-05 之后 60 天沪深300 +5%）
                fk, fl_lv = "rotate", "重点"
                ft = f"⚠ 红利大额流出{more} + 国家队在大额买沪深300：资金在从红利换到大盘，宽基规则让加仓时别犹豫，红利照评分买"
            elif nk.startswith("hi_buy"):
                fk, fl_lv = "dump_hi", "普通"
                ft = f"红利大额流出{more} + 国家队在高位护盘：别追大盘（2026-08 之后 60 天沪深300 −13%），红利照评分买，注意几天"
            elif nt_sell:
                fk, fl_lv = "dump_nt", "普通"
                ft = f"红利大额流出{more} + 国家队在卖：偏弱，别额外加钱，注意几天（2023 起同类之后 20 天多数跌）"
            else:
                fk, fl_lv = "dump", "普通"
                ft = f"红利大额流出{more}：注意几天，不用慌，照评分慢慢买（2023 起一笔比一笔大的流出，之后 60 天 6 次 5 次涨）"
        elif bigd >= 5 and f20 > 0:
            fk, ft, fl_lv = "chase", "近 20 天一直大额流入，追的人多：别追，照评分买", None
        elif nt_sell and f20 <= -2:
            fk, ft, fl_lv = "weak", "国家队在卖 + 红利资金也在流出：偏弱，别额外加钱", "普通"
        elif f20 <= -2 and (pos or 0) >= 0.6:
            fk, ft, fl_lv = "unloved", "资金在流出、没人要，位置又便宜：正是照评分慢慢买的时候", None
        elif f20 <= -2:
            fk, ft, fl_lv = "out", "资金在流出，红利暂时没人追", None
        else:
            fk, ft, fl_lv = "steady", "资金进出平稳，持续关注", None
        flow = {"key": fk, "text": ft, "level": fl_lv, "ups": ups, "dump": round(dump, 2), "f20": round(f20, 1), "burst": round(burst, 2), "big_days": bigd, "date": F["dates"][i]}
    # 标题：右侧 > 资金⚠ > 很便宜
    if right:
        head, hcls, level = "跌透转头", "g2", "重点"
        act = "⚠ 红利跌透后开始往上走（评分到过 14、位置便宜、站上 20 日线）：规则让加码时坚定加码，现金池里的闲钱可以分几周买进红利"
    elif flow and flow["key"] == "rotate":
        head, hcls, level, act = "红利流出 + 国家队买大盘" + (f"（第 {len(flow['ups'])} 笔更大的）" if len(flow["ups"]) > 1 else ""), "g2", "重点", flow["text"]
    elif flow and flow["key"] == "hide":
        head, hcls, level, act = "大盘资金躲进红利", "r1", "重点", flow["text"]
    elif flow and flow["level"] == "重点":
        # 第几笔更大的：邮件按"变了才发"，所以每多一笔更大的流入就会再发一封
        head, hcls, level, act = "突发大额 + 国家队" + (f"（第 {len(flow['ups'])} 笔更大的）" if len(flow["ups"]) > 1 else ""), "g2", "重点", flow["text"]
    elif n >= 4:
        head, hcls, level, act = lv, cls, "重点", txt
    elif flow and flow["key"] in ("dump", "dump_nt", "dump_hi"):
        nm = {"dump_nt": "大额流出 + 国家队在卖", "dump_hi": "大额流出 + 高位护盘", "dump": "大额流出"}[flow["key"]]
        head, hcls, level, act = nm, "r1" if flow["key"] != "dump" else "g1", "普通", flow["text"]
    elif flow and flow["level"] == "普通":
        head, hcls, level, act = "偏弱", "r1", "普通", flow["text"]
    else:
        head, hcls, level, act = lv, cls, None, txt
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "date": L["date"], "head": head, "cls": hcls, "level": level, "act": act,
        "lights": [{"name": a, "on": b, "text": c} for a, b, c in lights], "n": n, "lv": lv, "lv_text": txt,
        "right": right, "flow": flow, "nt": nk,
        "stats": [  # 回测（2018-05 起，红利低波100 全收益）：亮几个灯 → 一年后、一年内最多再跌
            {"n": "0~1 个", "y1": 7.1, "up": 81, "dd": -8.4, "worst": -21.2, "p10": 27},
            {"n": "2 个", "y1": 7.2, "up": 85, "dd": -6.7, "worst": -20.5, "p10": 31},
            {"n": "3 个", "y1": 13.1, "up": 98, "dd": -4.7, "worst": -10.5, "p10": 1},
            {"n": "4 个以上", "y1": 15.0, "up": 100, "dd": -2.9, "worst": -8.3, "p10": 0}],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{L['date']} 便宜灯 {n}/6（{lv}）；资金 {flow and flow['key']}；右侧 {right} → {head}")
    return data


if __name__ == "__main__":
    run()
