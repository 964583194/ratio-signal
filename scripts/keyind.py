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
        st = f"明天下单 {L['buy_amt']} 元" if L.get("buy_next") and L.get("buy_amt") else (f"已攒 {ow} 元" if ow else "")
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
    if NT and NT["latest"].get("pull"):
        p = NT["latest"]["pull"]
        cls = {"轻度回落": "h1", "明显回落": "r1", "持续流入": "g1"}.get(p["level"], "c0")
        exp.append(row("国家队大买后回落", f"5 日 {p['d5']:+,} 亿", p["level"], cls,
                       f"近 20 日 {p['d20']:+,} 亿。" + p["note"], "temp", NT["latest"]["date"]))
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
