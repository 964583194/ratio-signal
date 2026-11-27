"""关键指标一览（总览页最上面）：把分散在各页签的重要指标集中到一张表，分三组：
  规则   直接决定买卖的
  提醒   已上线、只作提醒，不改倍数
  实验   还在观察，2027-05-10 半年复盘再决定
输出 data/keyind.json。"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "keyind.json")
ZN = {"dbl": "翻倍买入区", "day": "加大买入区", "wk": "每周买入区", "pause": "暂停区"}


def _load(n):
    try:
        with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def row(name, value, status, cls, note, tab, date=None):
    return {"name": name, "value": value, "status": status, "cls": cls, "note": note, "tab": tab, "date": date}


def plain(r):
    """首页关键指标：一句大白话，说清"现在什么情况、要不要做什么"；原来的说明留在下面小字"""
    n, s = r["name"], r["status"]
    has = lambda *k: any(x in s for x in k)  # noqa: E731
    if "÷ 红利" in n:
        b = "创业板" if n.startswith("创业板") else "科创板"
        return (f"{b}涨多了，按规则卖一部分" if has("卖") else f"{b}非常便宜，每周翻倍买" if has("翻倍") else
                f"{b}很便宜，每周多买" if has("加大") else f"{b}比红利便宜，每周照常买" if has("买入") else
                f"{b}不够便宜，先不买，这份钱买红利" if has("暂停") else s)
    if n.startswith("破净率"):
        return "很多股票跌破净资产，到了历史少见的便宜，轮动更便宜时可以加码" if has("见底") else "还没便宜到见底标准，不加码"
    if n == "红利评分":
        return ("红利不便宜，暂时不攒新钱" if has("空仓") else "红利偏贵，明天要卖一部分" if has("减仓") else
                f"红利{s}档：每天攒钱，红利低波连跌两天后一起买")
    if n.startswith("A500"):
        return f"宽基{s.replace(' · ', '，每周买 ')}" if "倍" in s else f"宽基{s}"
    if n.startswith("黄金"):
        return "黄金暂不给建议，只看位置"
    if n.startswith("纳指"):
        return f"场内纳指 ETF 比实际值贵 {r['value']}，改买场外联接基金" if has("场外") else "场内价格正常，照常买"
    if n == "国家队加速流入":
        return "国家队越买越快，宽基额外多买 4 周" if has("加仓") else "国家队在买，但没有越买越快，不额外加仓"
    if n == "市场温度":
        return {"底部": "市场很冷、很便宜：分批买，备好钱", "偏冷": "市场偏冷，按规则买", "正常": "市场正常，按规则买",
                "偏热": "市场偏热，别额外加钱", "顶部": "市场过热，注意卖出信号"}.get(r["value"], s)
    if n == "见底灯":
        return f"6 个见底信号亮了 {r['value'].split('/')[0].strip()} 个：" + ("底部区" if has("底部") else "偏冷" if has("偏冷") else "还不算便宜")
    if n == "方向":
        return "还没看到好转，可能还要磨一段" if has("走弱") else "开始好转，可以加快买" if has("转暖", "回升") else s
    if n == "见顶灯":
        return "没有过热迹象" if has("没亮") else "有过热迹象，别追高"
    if n == "托底资金":
        return ("国家队在大举买入托底，跌了有人接，但不代表马上涨" if has("大幅流入") else "国家队在撤出，要谨慎" if has("撤出") else "国家队仓位变化不大")
    if n == "综合判断":
        return "看好的指标比看空的多，偏乐观" if has("积极") else "几个指标多数看空，谨慎" if has("谨慎") else "多空不明显"
    if n.startswith("红利位置"):
        return f"和近 5 年比，红利现在{s}"
    if n == "国家队大买后回落":
        return "国家队还在买，没有撤" if has("持续") else "国家队大买后开始撤一些，短期偏弱" if has("回落") else "没有大买后回落"
    if n == "国家队急买":
        return "国家队几天内突然大买：历史上之后多半上涨" if has("急买") else "最近几天没有突然大买"
    if n.startswith("银行"):
        return f"银行股估值{s}"
    return None


def run():
    R, K, D, A, G, N, T, E, C, NT, TS = (_load(f) for f in ("ratio.json", "kc.json", "dividend.json", "a500.json", "gold.json",
                                                          "ndx.json", "temp.json", "etf300.json", "combo.json", "ntf.json", "topsig.json"))
    rule, warn, exp = [], [], []
    for nm, d, tab in (("创业板50 ÷ 红利", R, "rotation"), ("科创50 ÷ 红利", K, "kc")):
        if d:
            L, th, P = d["latest"], d["params"]["th"], d.get("plan") or {}
            z = P.get("zone_name") or ZN.get(L["zone"], L["zone"])
            rule.append(row(nm, f"{L['ratio']:.4f}", z, "g1" if z != "暂停区" else "c0",
                            f"中位数 {th['mid']} 以下才买成长端；卖出线 {th['s1']}", tab, L["date"]))
    if T:
        pb = T["latest"]["bottom"]["values"].get("破净率")
        if pb is not None:
            rule.append(row("破净率（分位）", f"{pb * 100:.0f}%", "已见底" if pb >= .85 else "没见底", "g1" if pb >= .85 else "c0",
                            "≥85% 分位：轮动进加大 / 翻倍区时可以加码", "temp", T["latest"]["date"]))
    if D:
        L = D["latest"]
        ow = L.get("owed") or 0
        st = f"{L.get('next_label', '明天')}下单 {L['buy_amt']} 元" if L.get("buy_next") and L.get("buy_amt") else (f"已攒 {ow} 元" if ow else "")
        rule.append(row("红利评分", f"{L['score']:.2f}", L["tier"], "g1" if L["amount"] else "c0",
                        ("攒着一起买：" + st + "，" if st else "攒着一起买，") + "连跌 2 天后一起下单", "dividend", L["date"]))
    if A:
        L = A["latest"]
        rule.append(row("A500 便宜指数", f"{L['cheap']:.0f}", f"{L['zone']} · {L['mult']:g} 倍", "g1" if L["mult"] > 1 else "c0",
                        "≥60 买 2 倍，≥80 买 3 倍；<40 偏贵时止盈", "broad", L["date"]))
    if G:
        L = G["latest"]
        rule.append(row("黄金离年线", f"{L['dev'] * 100:+.0f}%", L["zone"], L.get("cls", "c0"),
                        "比年线高 25% 暂停、30% 卖 1/3；低 5% 以上 1.5 倍", "gold", L["date"]))
    if N:
        pr = (N.get("premium") or {}).get("value")
        if pr is not None:
            rule.append(row("纳指场内溢价", f"{pr * 100:.1f}%", "买场外联接" if pr > .05 else "可以买场内", "h1" if pr > .05 else "c0",
                            "超过 5% 改买场外联接基金", "ndx", N["latest"]["date"]))
    if NT:
        L = NT["latest"]
        rule.append(row("国家队加速流入", f"{L['pct'] * 100:.0f}% 分位", L["state"], L["cls"],
                        "≥90% 分位、新的一段 → 宽基额外买 4 周的量", "temp", L["date"]))
    if T:
        L = T["latest"]
        warn.append(row("市场温度", L["zone"], L["zone"] + "区", L["cls"], "→ " + L["action"].split("；")[0] + "（五档：底部 / 偏冷 / 正常 / 偏热 / 顶部）", "temp", L["date"]))
        b = L["bottom"]
        warn.append(row("见底灯", f"{b['count']} / 6", "底部" if b["count"] >= 4 else "偏冷" if b["count"] >= 2 else "没亮够", "g1" if b["count"] >= 2 else "c0",
                        ("亮着：" + "、".join(b["lit"]) + "。" if b["lit"] else "") + "亮 2~3 个偏冷，≥4 个底部", "temp", L["date"]))
        dr = L.get("dir") or {}
        warn.append(row("方向", f"{dr.get('n_up', 0)} / 3 回升", dr.get("label", "—"), "g1" if dr.get("label") == "转暖" else "c0",
                        dr.get("text", "") + "。只在偏冷 / 底部区看：3 个都回升 = 转暖", "temp", L["date"]))
    if TS:
        L = TS["latest"]
        warn.append(row("见顶灯", f"{L['count']} / 7", "接近顶部" if L["count"] >= 3 else "偏热" if L["count"] == 2 else "没亮够", "r1" if L["count"] >= 3 else "h1" if L["count"] == 2 else "c0",
                        ("亮着：" + "、".join(L["lit"]) + "。" if L["lit"] else "") + "亮 2 个偏热，≥3 个接近顶部", "temp", L["date"]))
    if E:
        L = E["latest"]
        warn.append(row("托底资金", f"20 日 {L['chg20'] * 100:+.0f}%", L["zone"].split("·")[0], L["cls"],
                        "份额 20 日减少 ≥15% = 撤出，之后 60 日平均 −4%", "temp", L["date"]))
    if C:
        L = C["latest"]
        exp.append(row("综合判断", f"多 {L['bull']} · 空 {L['bear']}", L["level"], L["cls"],
                       "只看两头：积极之后半年历史上全部上涨，谨慎之后平均 −13%", "temp", L["date"]))
    if D and D["latest"].get("pos"):
        P_ = D["latest"]["pos"]
        st_ = {x["zone"]: x for x in D.get("pos_stats", [])}.get(P_["zone"], {})
        exp.append(row("红利位置（股息率 + 利差）", f"{P_['value']*100:.0f}%", P_["zone"],
                       "g1" if P_["value"] >= .6 else "h1" if P_["value"] < .4 else "c0",
                       f"→ {P_['advice']}。利差在近 5 年高于 {P_['sp_pct']*100:.0f}% 的日子，股息率高于 {P_['dy_pct']*100:.0f}%。"
                       + (f"历史上这一档之后一年平均 {st_['r12']*100:+.1f}%（{st_['up12']*100:.0f}% 上涨）。" if st_.get("n") else "")
                       + "只作参考，不改买卖（评分空仓时照样不买）", "dividend", P_["date"]))
    if NT and NT["latest"].get("pull"):
        p = NT["latest"]["pull"]
        cls = {"轻度回落": "h1", "明显回落": "r1", "持续流入": "g1"}.get(p["level"], "c0")
        exp.append(row("国家队大买后回落", f"5 日 {p['d5']:+,} 亿", p["level"], cls,
                       (f"已连续 {p['days']} 天（{p['since']} 起），满 2 天发邮件提醒。" if p.get("days") else "") +
                       f"近 20 日 {p['d20']:+,} 亿。" + p["note"] + ("。想减仓的话这时减比较合适（参考：减 1/3、60 天后买回，回测不稳定）" if p.get("days", 0) >= 2 else ""), "temp", NT["latest"]["date"]))
    if NT and NT["latest"].get("rush"):
        r = NT["latest"]["rush"]
        s1 = r["stats"]["急买第一天"]
        exp.append(row("国家队急买", f"占成交额 {(r['r5'] or 0)*100:.2f}%", "急买中" if r["on"] else "没有", "g1" if r["on"] else "c0",
                       (f"已连续 {r['days']} 天（{r['since']} 起）。" if r["on"] else "") +
                       f"4 只沪深300 ETF 近 5 日净申购 {r['d5']:+,} 亿，占两市近 5 日成交额的 1% 以上算急买（门槛随市场大小自动变）。"
                       + (f"2023 年起 {s1['n']} 段，已满 60 天的 {s1['60']['n']} 段之后 60 日沪深300 平均 {s1['60']['avg']*100:+.1f}%（{s1['60']['up']*100:.0f}% 上涨）。" if s1.get("60") else "")
                       + "样本少，只作提醒，不改倍数", "temp", NT["latest"]["date"]))
    BK = _load("bank.json")
    if BK:
        L = BK["latest"]
        cls = {"很便宜": "g1", "偏便宜": "g1", "偏贵": "h1"}.get(L["zone"], "c0")
        exp.append(row("银行便宜指数", f"{L['cheap']:.0f}", L["zone"], cls,
                       f"股息率 − 十年国债 = {L['spread']:.2f} 个百分点（近 10 年 {L['sp_pct'] * 100:.0f}% 分位）；不占比例，只作提醒", "bond", L["date"]))
    for r in rule + warn + exp:
        try:
            r["plain"] = plain(r)
        except Exception as e:  # noqa: BLE001
            print(f"大白话生成失败 {r['name']}：{e}")
    data = {"updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
            "groups": [{"key": "rule", "title": "规则", "desc": "直接决定买卖", "rows": rule},
                       {"key": "warn", "title": "提醒", "desc": "已上线，只作提醒，不改倍数", "rows": warn},
                       {"key": "exp", "title": "实验", "desc": "还在观察，2027-05-10 半年复盘再决定要不要进规则", "rows": exp}]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：规则 {len(rule)}、提醒 {len(warn)}、实验 {len(exp)}")
    return data


if __name__ == "__main__":
    run()
