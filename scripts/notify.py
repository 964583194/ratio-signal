"""
信号提醒与周报：在仓库里新建 Issue 并 @ 仓库主人，GitHub 会把它发到主人的通知邮箱。

每次运行最多发一封，内容合并整理：
- 信号变化：和上次保存的状态（data/state.json）比较，分“要操作的”（定投板块）和“提醒”（市场温度、见顶灯、
  托底资金、黄金资金、我的基金、海外小仓位）两组。
- 到期复盘（data/reminders.json）：日期到了就并进同一封。
- 周报：环境变量 REPORT=1 时发（周五早上 8 点多），按周四收盘的信号，提醒周五 15:00 前下单（场外基金按周五净值）；
  开头是下单提示、一句话总结和“每 1000 元本周下单清单”，当次变化和到期复盘也并进周报，不再另发。
- 平时的提醒分组：今天就做（卖出、红利打分）/ 周五再定（其他定投板块，周中变化不用动，以周报为准）/ 提醒 / 数据源；不再附全部状态表。
- 第一次运行（还没有 state.json）发一封“提醒已开启”。
同时写 data/plan.json（每周下单清单，每 1000 元），给总览页按自己的预算换算。
只在 GitHub Actions 里真正发送；本地运行只打印。
"""
import datetime as dt
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state.json")
REPO = os.environ.get("GITHUB_REPOSITORY", "964583194/ratio-signal")
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", REPO.split("/")[0])
TOKEN = os.environ.get("GITHUB_TOKEN") if os.environ.get("GITHUB_ACTIONS") == "true" else None
PAGE = f"https://{OWNER}.github.io/{REPO.split('/')[1]}/"
TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()


def load(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def pc(x, d=1):
    return f"{x * 100:.{d}f}%"


# ---------------------------------------------------------------- 各页签的当前状态
def rotation(d, g, tab):
    """返回 (状态key, 一句话现状, 本周操作, 页签)。状态里带上阈值生效日，半年调整时也会提醒。"""
    L, P, PL = d["latest"], d["params"], d["plan"]
    T, r = P["th"], L["ratio"]
    gap = []
    if r >= T["mid"]:
        gap.append(f"距每周买入线 {T['mid']} 还需跌 {pc(1 - T['mid'] / r)}")
    if r < T["s1"]:
        gap.append(f"距卖出线 {T['s1']} 还需涨 {pc(T['s1'] / r - 1)}")
    act = "；".join(PL["actions"] + PL["warn"]) + ("；" + "，".join(gap) if gap else "")
    state = f"{PL['zone_name']}|阈值{P['th_date']}"
    th = f"（阈值 {P['th_date']} 起：每周买 <{T['mid']}，加大 <{T['day']}，翻倍 <{T['dbl']}，卖出 {T['s1']}/{T['s2']}/{T['s3']}）"
    return state, f"信号值 {r:.4f}（{PL['zone_name']}）", act + th, tab


def dividend(d):
    L = d["latest"]
    es = L.get("eff", L["score"])
    amt = f"{L['amount']:.0f} 元/天" if L["amount"] else ("分批卖出" if es <= 6 else "暂停定投")
    wait = "（新档位还没连续 2 天，先按上一档）" if L.get("pending") else ""
    return L["tier"], f"评分 {L['score']:.2f} / 20（{L['tier']}）{wait}", f"{L['tier']} · {amt}", "dividend"


def a500(d):
    L = d["latest"]
    ma = "，已有效跌破年线" if L["below"] else ""
    return L["zone"], f"便宜指数 {L['cheap']:.1f}（{L['zone']}）", f"{L['action']}{ma}", "a500"


def overseas(d):
    """海外小仓位：只有各基金的状态变化才提醒"""
    fs = d["funds"]
    state = "|".join(f"{f['name'][:4]}{f['latest']['zone']}" for f in fs)
    now = "；".join(f"{f['name']} 回撤 {pc(f['latest']['dd'])}（{f['latest']['zone']}）" for f in fs)
    hot = [f["name"] for f in fs if f["latest"]["zone"] == "过热"]
    add = [f["name"] for f in fs if f["latest"]["zone"] in ("大幅回撤", "深度回撤")]
    act = ("；".join(([f"{'、'.join(hot)} 过热，暂停加钱"] if hot else []) + ([f"{'、'.join(add)} 回撤较大，有余钱可以多加"] if add else []))
           or "都照常持有")
    pr = d.get("premium")
    if pr and pr["value"] > 0.05:
        act += f"；亚太精选场内 ETF 溢价 {pc(pr['value'])}，买场外联接"
    return state, now, act, "funds.html#os"


def topsig(d):
    """见顶信号灯：亮灯个数变化就提醒"""
    L = d["latest"]
    lit = "、".join(L["lit"]) or "无"
    now = f"{L['count']} / 7 个信号亮着（{lit}）"
    return f"亮{L['count']}个", now, L["action"] + "（只作提醒，不改规则）", "temp"


def etf300(d):
    """托底资金（国家队）：状态变化就提醒（先观察，不进规则）"""
    L = d["latest"]
    pct = "—" if L["pct"] is None else pc(L["pct"], 0)
    now = (f"头部沪深300 ETF 规模 {L['size']:,} 亿，占沪深300 流通市值 {L['ratio']:.2f}%（近 252 日分位 {pct}），"
           f"近 20 日份额 {'+' if (L['chg20'] or 0) > 0 else ''}{pc(L['chg20'])}")
    hs, mk = load("hs300.json") or {}, load("market.json") or {}
    cheap = (hs.get("latest") or {}).get("cheap")
    return L["zone"], now, f"{L['action']}。暂定判断：{judge(L['zone'], cheap, mk.get('pb_hot'))}（只作参考，不改规则和倍数）", "temp"


def ntf(d):
    """国家队流向：只提醒加速流入新的一段（加仓提醒）"""
    L = d["latest"]
    now = f"4 只沪深300 ETF 流入加速度 {L['acc']:+.1f} 亿/天（近一年 {pc(L['pct'], 0)} 分位），近 20 日净申购 {L['f4_20']:+,} 亿"
    return L["key"], now, L["action"] + "（只作提醒，不改倍数）", "temp"


def judge(zone, cheap, pb_hot):
    """和页面上的暂定判断同一张表：国家队状态 × 沪深300 便宜指数"""
    lv = "mid" if cheap is None else "cheap" if cheap >= 60 else "mid" if cheap >= 40 else "dear"
    T = {"大幅流入·托底": {"cheap": "有人托底，按规则买可以放心执行；不额外加钱，短期 1~3 个月可能还会下探", "mid": "有人托底，照常买", "dear": "少见：托底资金在买、但指数不便宜，照常"},
         "重仓持有": {"cheap": "下跌有人接，照常买", "mid": "照常", "dear": "托底资金还在，但已不便宜，按规则少买"},
         "撤出中": {"cheap": "接盘的人在减少，别急着加码", "mid": "偏谨慎，照常", "dear": "偏热：少买，止盈可以积极一点"},
         "低仓观望": {"cheap": "没人托底，按规则买，但要接受更大波动", "mid": "照常", "dear": "偏热，按规则少买"}}
    t = T.get(zone, {}).get(lv, "跟着便宜指数走，这个指标不额外说什么")
    if pb_hot and zone in ("大幅流入·托底", "重仓持有"):
        t += "；破净率也已见底"
    return t


def ndx(d, prev_prem):
    L, pr = d["latest"], d.get("premium")
    # 溢价率用滞后区间，避免在 5% 附近来回提醒：>5% 记为“高”，≤3% 记为“低”，中间保持上次
    prem = prev_prem or "未知"
    if pr:
        prem = "高" if pr["value"] > 0.05 else "低" if pr["value"] <= 0.03 else (prev_prem or "中")
    state = f"{L['action']}|溢价{prem}"   # 只在该做的事变了才提醒（回调 ↔ 接近高点都是照常定投，不提醒）
    act = L["action"]
    if pr and prem == "高":
        act += f"；场内ETF溢价 {pc(pr['value'])}，改买场外联接基金"
    elif pr and prem == "低":
        act += f"；场内ETF溢价 {pc(pr['value'])}，可以买场内"
    return state, f"回撤 {pc(L['dd'])}（{L['zone']}），{'跌破' if L['below'] else '位于'}年线", act, "ndx"


def gold(d):
    """黄金六档：结论一变就提醒（ETF 资金恐慌撤出、涨得极端可以卖一部分 都在里面）"""
    L = d["latest"]
    return L["zone"], f"{L['why']}；离最高点 {pc(L['dd'])}，比年线{'高' if L['dev'] >= 0 else '低'} {pc(abs(L['dev']))}", L["action"], "gold"


def bond(d):
    L = d["latest"]
    return L["zone"], f"十年国债 {L['close']:.2f}%，比近一年均值{'高' if L['dev'] >= 0 else '低'} {abs(L['dev']):.0f}bp", L["action"], "bond"


def short(n):
    return re.sub(r"ETF发起式联接|ETF联接|发起式|\(QDII\)|（QDII）|混合|股票|指数|[AC]$", "", n)


# 组合比例（2026-11-12 纳指移出组合，其余按原比例放大）；纳指100 单独小额定投，不占比例
WEIGHTS = {"创业板轮动": 31.25, "科创板轮动": 18.75, "红利打分": 18.75, "黄金": 18.75, "A500 / 沪深300": 12.5}


def collect(prev):
    out = {}
    pairs = [("创业板轮动", "ratio.json", lambda d: rotation(d, "创业板50", "rotation")),
             ("科创板轮动", "kc.json", lambda d: rotation(d, "科创50", "kc")),
             ("红利打分", "dividend.json", dividend),
             ("A500 / 沪深300", "a500.json", lambda d: a500(d)[:3] + ("broad",)),   # 两个用同一个便宜指数
             ("纳指100", "ndx.json", lambda d: ndx(d, (prev.get("纳指100") or {}).get("prem"))),
             ("黄金", "gold.json", gold),
             ("债基", "bond.json", bond),
             ("海外小仓位", "overseas.json", overseas),
             ("托底资金（国家队）", "etf300.json", etf300),
             ("国家队流向", "ntf.json", ntf),
             ("见顶信号灯", "topsig.json", topsig)]
    for name, f, fn in pairs:
        d = load(f)
        if not d:
            continue
        state, now, act, tab = fn(d)
        out[name] = {"state": state, "now": now, "act": act, "tab": tab, "date": d["latest"]["date"]}
        if name == "纳指100":
            out[name]["prem"] = state.split("溢价")[-1]
    mf = load("myfunds.json")
    if mf:
        F = mf["funds"]
        add = sorted(f["code"] for f in F if f["tag"] == "add")
        cut = sorted(f["code"] for f in F if f["tag"] == "cut")
        nm = lambda cs: "、".join(short(f["name"]) for f in F if f["code"] in cs) or "无"  # noqa: E731
        c = mf["count"]
        out["我的基金"] = {"state": "加:" + ",".join(add) + "|减:" + ",".join(cut), "tab": "funds.html", "date": mf["updated"][:10],
                       "now": f"{len(F)} 只：可以加 {c['add']}、照常 {c['hold']}、先别加 {c['wait']}、可以减 {c['cut']}",
                       "act": f"可以加：{nm(add)}" + (f"；可以减：{nm(cut)}" if cut else "")}
    m, t = load("market.json"), load("temp.json")
    if t:
        L = t["latest"]
        pb = ""
        if m:
            pb = f"；破净率 {m['extra']['pb_val'] * 100:.1f}%（{'已到' if m['pb_hot'] else '未到'}见底标准，轮动{'可以' if m['pb_hot'] else '暂不'}加码）"
        out["市场温度"] = {"state": L["zone"], "tab": "temp", "date": L["date"],
                       "now": f"{L['zone']}区：见底灯 {L['bottom']['count']}/6，见顶灯 {L['top']['count']}/7，方向{L['dir']['label']}（{L['dir']['text']}）",
                       "act": L["action"] + "（只作提醒，不改规则）" + pb}
    h = load("health.json") or {}
    stale = [v["name"] for v in (h.get("items") or {}).values()
             if not v.get("ref") and (v.get("stale_days") is None or v["stale_days"] > 12)]
    nt, hs = load("ntf.json"), load("hs300.json")
    try:
        if nt and hs and (dt.date.fromisoformat(hs["latest"]["date"]) - dt.date.fromisoformat(nt["latest"]["date"])).days > 7:
            stale.append("国家队流向（ETF 份额 / 净值）")
    except Exception:  # noqa: BLE001
        pass
    out["数据源"] = {"state": "异常:" + "、".join(stale) if stale else "正常",
                    "now": f"{len(h.get('items') or {})} 项", "act": "请查看 Actions 运行记录" if stale else "无需处理",
                    "tab": "", "date": h.get("updated", "")[:10]}
    return out


# ---------------------------------------------------------------- 发 Issue
def gh(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "ratio-signal", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"null")


def post(title, body, prefix):
    body += f"\n\n[打开信号看板]({PAGE}) · 提醒给 @{OWNER}"
    if not TOKEN:
        print(f"（本地运行，不发送）\n# {title}\n{body}\n")
        return
    try:     # 同类旧提醒关掉，只保留最新一条在列表里（邮件不受影响）
        for it in gh("GET", "/issues?state=open&per_page=50") or []:
            if it["title"].startswith(prefix) and "pull_request" not in it:
                gh("PATCH", f"/issues/{it['number']}", {"state": "closed"})
    except Exception as e:  # noqa: BLE001
        print(f"关闭旧提醒失败：{e}")
    it = gh("POST", "/issues", {"title": title, "body": body})
    print(f"已发送：{title} → {it.get('html_url')}")


def brief(act):
    """操作说明只留第一句（去掉“距买入线还需…”“阈值…”这类细节，网页上有）"""
    act = re.split(r"；距|（阈值", act)[0]
    return re.sub(r"（只作(提醒|参考)[^）]*）", "", act)


def table(cur):
    rows = ["| 板块 | 现在 | 怎么做 |", "|---|---|---|"]
    for name, v in cur.items():
        if name == "数据源" and "无需处理" in v["act"]:
            continue
        link = (f"[{name}]({PAGE}{v['tab']})" if ".html" in v["tab"] else f"[{name}]({PAGE}#{v['tab']})") if v["tab"] else name
        w = f"（{WEIGHTS[name]:g}%）" if name in WEIGHTS else "（不占比例）" if name == "纳指100" else ""
        rows.append(f"| {link}{w} | {v['now']} | {brief(v['act'])} |")
    return "\n".join(rows)


OPS = list(WEIGHTS) + ["纳指100", "债基"]          # 要操作的（定投板块）


def build_plan(cur):
    """每周下单清单（每 1000 元）：按组合比例和各板块本周信号。没买的钱放红利低波100；红利打分空仓的钱存着。"""
    base, rows = 1000, []
    for name, f, g in (("创业板轮动", "ratio.json", "创业板50"), ("科创板轮动", "kc.json", "科创50")):
        d = load(f)
        if not d:
            continue
        share = base * WEIGHTS[name] / 100
        acts = d["plan"]["actions"]
        first = acts[0] if acts else ""
        fixed = sum(int(x) for x in re.findall(r"加码\s*(\d+)\s*元", "；".join(acts)))
        if "买" + g in first and "暂停买" + g not in first:
            rows.append({"name": name, "what": g, "amt": share, "fixed": fixed, "note": d["plan"]["zone_name"]})
        else:
            rows.append({"name": name, "what": "红利低波100", "amt": share, "fixed": 0, "note": f"{d['plan']['zone_name']}，这部分买红利"})
    dv = load("dividend.json")
    if dv:
        share = base * WEIGHTS["红利打分"] / 100
        L = dv["latest"]
        m = (L["amount"] or 0) / 200
        if L.get("eff", L["score"]) <= 6:
            rows.append({"name": "红利打分", "what": "红利低波100", "amt": 0, "fixed": 0, "note": "评分很低，按页签分批卖出；这部分存着"})
        elif m == 0:
            rows.append({"name": "红利打分", "what": "红利低波100", "amt": 0, "fixed": 0, "note": f"{L['tier']}，暂停，这部分存着（现金池）"})
        else:
            rows.append({"name": "红利打分", "what": "红利低波100", "amt": share * m, "fixed": 0, "note": f"{L['tier']} {m:g} 倍，分到每个交易日买", "daily": True})
    for name, f, what, w in (("A500 / 沪深300", "a500.json", "A500（或沪深300）", "A500 / 沪深300"), ("黄金", "gold.json", "黄金", "黄金")):
        d = load(f)
        if not d:
            continue
        share, mm = base * WEIGHTS[w] / 100, d["latest"]["mult"]
        rows.append({"name": name, "what": what, "amt": share * mm, "fixed": 0,
                     "note": (d["latest"]["zone"] + "：" if name == "黄金" else "") + d["latest"]["action"]})
        if mm < 1:
            rows.append({"name": name, "what": "红利低波100", "amt": share * (1 - mm), "fixed": 0, "note": "没买完的部分买红利"})
    side = []
    nd = load("ndx.json")
    if nd:     # 纳指100 不占组合比例，单独小额定投
        pr = (nd.get("premium") or {}).get("value")
        side.append({"name": "纳指100", "what": "纳指100 场外联接" if pr and pr > .05 else "纳指100",
                     "note": "不占比例，单独小额定投（每天约 20~100 元）" + (f"；场内溢价 {pr * 100:.1f}%，买场外" if pr and pr > .05 else "")})
    nt = load("ntf.json")
    if nt and nt["latest"].get("fresh") and not nt["latest"].get("hot") and nt["latest"].get("episode"):
        ds = [x[0] for x in nt["series"]]
        ep = nt["latest"]["episode"]["date"]
        k = len(ds) - 1 - ds.index(ep) if ep in ds else 99
        if k < 10:     # 4 周的量分 2 周买完
            rows.append({"name": "国家队加仓", "what": "A500（或沪深300）", "amt": base * WEIGHTS["A500 / 沪深300"] / 100 * 2, "fixed": 0,
                         "note": f"国家队加速流入（{ep} 开始）：额外 4 周的量分 2 周买，这是第 {1 if k < 5 else 2} / 2 周"})
    for r in rows:
        r["amt"] = round(r["amt"])
    data = {"date": TODAY, "base": base, "rows": rows, "side": side,
            "buy": sum(r["amt"] for r in rows), "fixed": sum(r["fixed"] for r in rows),
            "note": "金额按每周预算等比例换算；“另外加码”是固定金额（破净率见底时），不随预算变。超出预算的部分从备用金出。"}
    with open(os.path.join(DATA, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def plan_md(P):
    lines = ["| 板块 | 买什么 | 金额 | 说明 |", "|---|---|---|---|"]
    for r in P["rows"]:
        amt = f"{r['amt']} 元" + ("（分到每天）" if r.get("daily") else "") + (f" + 另外加码 {r['fixed']} 元" if r["fixed"] else "")
        lines.append(f"| {r['name']} | {r['what']} | {amt} | {r['note']} |")
    over = P["buy"] - P["base"]
    lines.append(f"\n合计 {P['buy']} 元" + (f"（比预算多 {over} 元，从备用金出）" if over > 0 else f"（预算里有 {-over} 元没花，存着）" if over < 0 else "")
                 + (f"，另外加码 {P['fixed']} 元" if P["fixed"] else "") + "。按自己的预算等比例换算，网页总览可以直接填预算。")
    for r in P.get("side") or []:
        lines.append(f"\n另外：**{r['name']}**（{r['what']}）{r['note']}。")
    return "\n".join(lines)


SELL = re.compile(r"卖|减|止盈|转红利")


def group_of(n, b, cur, report):
    """今天就做：卖出类、红利打分（按日买）；周五再定：其他定投板块（周五按周四收盘下单）"""
    if n == "数据源":
        return "数据源"
    if n in OPS or (n == "国家队流向" and b.startswith("加仓")):
        if SELL.search(re.split(r"；距|（阈值", cur[n]["act"])[0]) or n == "红利打分":
            return "今天就做"
        return "本周下单" if report else "周五再定"
    return "提醒"


def change_lines(changes, cur, prev, report=False):
    """按“今天就做 / 周五再定（周报里叫本周下单）/ 提醒 / 数据源”分组的变化说明"""
    mf = load("myfunds.json") or {"funds": []}
    names = {f["code"]: short(f["name"]) for f in mf["funds"]}
    groups = {"今天就做": [], "本周下单": [], "周五再定": [], "提醒": [], "数据源": []}
    for n, a, b in changes:
        g = group_of(n, b, cur, report)
        link = f"{PAGE}{cur[n]['tab']}" if ".html" in cur[n]["tab"] else f"{PAGE}#{cur[n]['tab']}"
        if n == "我的基金":
            pa, pb = [dict(x.split(":") for x in st.split("|")) for st in (a, b)]
            sa, sb = (set(filter(None, pa["加"].split(","))), set(filter(None, pa["减"].split(",")))), \
                     (set(filter(None, pb["加"].split(","))), set(filter(None, pb["减"].split(","))))
            parts = []
            for lab, x, y in (("新变成可以加", sb[0], sa[0]), ("不再是可以加", sa[0], sb[0]), ("新出现可以减", sb[1], sa[1]), ("不再是可以减", sa[1], sb[1])):
                if x - y:
                    parts.append(f"{lab}：{'、'.join(names.get(c, c) for c in sorted(x - y))}")
            groups[g].append(f"- **[我的基金]({link})**：{'；'.join(parts)}")
            continue
        tail = "（周五早上按周四收盘再确认，到时以周报为准，现在不用动）" if g == "周五再定" else ""
        groups[g].append(f"- **[{n}]({link})**：{a.replace('|', '，')} → **{b.replace('|', '，')}**\n  - {cur[n]['now']}\n  - **{brief(cur[n]['act'])}**{tail}")
    return groups


def headline():
    """一句话总结：市场温度 + 黄金 + 我的基金"""
    out = []
    t, g, mf = load("temp.json"), load("goldmodel.json"), load("myfunds.json")
    if t:
        out.append(f"- **市场温度**：{t['latest']['verdict']}")
    if g:
        out.append(f"- **黄金**：{g['latest']['verdict']}")
    cb = load("combo.json")
    if cb and cb["latest"]["level"] in ("积极", "谨慎"):
        lv = cb["latest"]["level"]
        out.append(f"- **综合判断：{lv}**（好几个指标同时{'看好' if lv == '积极' else '看坏'}）→ "
                   + ("按规则该加的放心加" if lv == "积极" else "别额外加钱，止盈可以果断"))
    if mf:
        c = mf["count"]
        add = [short(f["name"]) for f in mf["funds"] if f["tag"] == "add"]
        out.append(f"- **我的基金**：可以加 {c['add']}（{'、'.join(add) or '无'}）、照常 {c['hold']}、先别加 {c['wait']}、可以减 {c['cut']}")
    return "\n".join(out)


def main():
    prev = load("state.json")
    first = prev is None
    prev = prev or {}
    cur = collect(prev)
    P = build_plan(cur)
    changes = [(n, prev[n]["state"], v["state"]) for n, v in cur.items()
               if n in prev and prev[n].get("state") != v["state"]]
    rem = load("reminders.json") or []
    due = [r for r in rem if not r.get("done") and r["date"] <= TODAY]
    report = os.environ.get("REPORT") == "1" and not first
    G = change_lines(changes, cur, prev, report) if changes else {}
    chg = "\n\n".join(f"**{k}**\n\n" + "\n".join(v) for k, v in G.items() if v)
    dues = "\n\n".join(f"### {r['title']}\n\n{r['body']}" for r in due)

    if first:
        post(f"【提醒已开启】{TODAY} 信号看板", "以后信号有变化时会发这样的邮件，每周五早上还会发一封周报。下面是当前状态：\n\n"
             + table(cur), "【提醒已开启】")
    elif report:
        body = ("**今天（周五）15:00 前下单**：场外基金 15:00 前买按今天净值成交。按周四收盘的信号，周中的变化以这封为准。\n\n"
                + headline() + "\n\n### 本周下单清单（每 1000 元）\n\n" + plan_md(P)
                + (f"\n\n### 这周有变化的\n\n{chg}" if chg else "") + (f"\n\n## 到期复盘\n\n{dues}" if dues else "")
                + "\n\n### 各板块现在\n\n" + table(cur)
                + "\n\n轮动、A500 / 沪深300、黄金每周五买一次；红利打分按日买；卖出信号出现时当天另发邮件。没买完的钱都放红利低波100。")
        post(f"【周报】{TODAY} 今天 15:00 前下单" + ("（含变化）" if chg else "") + ("（含到期复盘）" if due else ""), body, "【周报】")
    elif changes or due:
        tt = []
        for k, lab in (("今天就做", "今天就做"), ("周五再定", "周五再定"), ("提醒", "提醒"), ("数据源", "数据源")):
            ns = [n for n, _, b in changes if group_of(n, b, cur, False) == k]
            if ns:
                tt.append(f"{lab}：" + "、".join(ns))
        if due:
            tt.append("到期复盘")
        body = (chg + (f"\n\n## 到期复盘\n\n{dues}" if dues else "")
                + ("" if G.get("今天就做") else "\n\n今天没有要马上做的事，定投照常等周五早上的周报。")).lstrip()
        post(f"【{'要操作' if G.get('今天就做') else '提醒'}】{TODAY} " + "；".join(tt), body, ("【提醒】", "【要操作】", "【信号提醒】"))
    else:
        print("信号没有变化，不发提醒")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    if due and not first:
        for r in due:
            r["done"], r["sent"] = True, TODAY
        with open(os.path.join(DATA, "reminders.json"), "w", encoding="utf-8") as f:
            json.dump(rem, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
