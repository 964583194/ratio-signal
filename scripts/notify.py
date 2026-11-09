"""
信号提醒与周报：在仓库里新建 Issue 并 @ 仓库主人，GitHub 会把它发到主人的通知邮箱。

- 信号变化提醒：和上次保存的状态（data/state.json）比较，有变化才发。
- 周报：环境变量 REPORT=1 时发（工作流在周五早上设置）。
- 第一次运行（还没有 state.json）发一封“提醒已开启”，附当前状态，用来确认邮箱能收到。
只在 GitHub Actions 里真正发送；本地运行只打印。
"""
import datetime as dt
import json
import os
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
    amt = f"{L['amount']:.0f} 元/天" if L["amount"] else ("分批卖出" if L["score"] <= 6 else "暂停定投")
    return L["tier"], f"评分 {L['score']:.2f} / 20（{L['tier']}）", f"{L['tier']} · {amt}", "dividend"


def a500(d):
    L = d["latest"]
    ma = "，已有效跌破年线" if L["below"] else ""
    return L["zone"], f"便宜指数 {L['cheap']:.1f}（{L['zone']}）", f"{L['action']}{ma}", "a500"


def ndx(d, prev_prem):
    L, pr = d["latest"], d.get("premium")
    # 溢价率用滞后区间，避免在 5% 附近来回提醒：>5% 记为“高”，≤3% 记为“低”，中间保持上次
    prem = prev_prem or "未知"
    if pr:
        prem = "高" if pr["value"] > 0.05 else "低" if pr["value"] <= 0.03 else (prev_prem or "中")
    state = f"{L['zone']}|{'跌破年线' if L['below'] else '年线上方'}|溢价{prem}"
    act = L["action"]
    if pr and prem == "高":
        act += f"；场内ETF溢价 {pc(pr['value'])}，改买场外联接基金"
    elif pr and prem == "低":
        act += f"；场内ETF溢价 {pc(pr['value'])}，可以买场内"
    return state, f"回撤 {pc(L['dd'])}（{L['zone']}），{'跌破' if L['below'] else '位于'}年线", act, "ndx"


def gold(d):
    L = d["latest"]
    return L["zone"], f"回撤 {pc(L['dd'])}，比年线{'高' if L['dev'] >= 0 else '低'} {pc(abs(L['dev']))}（{L['zone']}）", L["action"], "gold"


def bond(d):
    L = d["latest"]
    return L["zone"], f"十年国债 {L['close']:.2f}%，比近一年均值{'高' if L['dev'] >= 0 else '低'} {abs(L['dev']):.0f}bp", L["action"], "bond"


WEIGHTS = {"创业板轮动": 25, "科创板轮动": 15, "纳指100": 20, "红利打分": 15, "黄金": 15, "沪深300": 5, "中证A500": 5}


def collect(prev):
    out = {}
    pairs = [("创业板轮动", "ratio.json", lambda d: rotation(d, "创业板50", "rotation")),
             ("科创板轮动", "kc.json", lambda d: rotation(d, "科创50", "kc")),
             ("红利打分", "dividend.json", dividend),
             ("中证A500", "a500.json", a500),
             ("沪深300", "hs300.json", lambda d: a500(d)[:3] + ("hs300",)),
             ("纳指100", "ndx.json", lambda d: ndx(d, (prev.get("纳指100") or {}).get("prem"))),
             ("黄金", "gold.json", gold),
             ("债基", "bond.json", bond)]
    for name, f, fn in pairs:
        d = load(f)
        if not d:
            continue
        state, now, act, tab = fn(d)
        out[name] = {"state": state, "now": now, "act": act, "tab": tab, "date": d["latest"]["date"]}
        if name == "纳指100":
            out[name]["prem"] = state.split("溢价")[-1]
    h = load("health.json") or {}
    stale = [v["name"] for v in (h.get("items") or {}).values()
             if not v.get("ref") and (v.get("stale_days") is None or v["stale_days"] > 12)]
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


def table(cur):
    rows = ["| 页签 | 比例 | 现状 | 操作 |", "|---|---|---|---|"]
    for name, v in cur.items():
        link = f"[{name}]({PAGE}#{v['tab']})" if v["tab"] else name
        w = f"{WEIGHTS[name]}%" if name in WEIGHTS else ""
        rows.append(f"| {link} | {w} | {v['now']} | {v['act']} |")
    return "\n".join(rows)


def main():
    prev = load("state.json")
    first = prev is None
    prev = prev or {}
    cur = collect(prev)

    changes = [(n, prev[n]["state"], v["state"]) for n, v in cur.items()
               if n in prev and prev[n].get("state") != v["state"]]
    if first:
        post(f"【提醒已开启】{TODAY} 信号看板", "以后信号有变化时会发这样的邮件，每周五早上还会发一封周报。下面是当前状态：\n\n"
             + table(cur), "【提醒已开启】")
    elif changes:
        names = "、".join(n for n, _, _ in changes)
        lines = [f"- **{n}**：{a.replace('|', '，')} → **{b.replace('|', '，')}**\n  - 现在：{cur[n]['now']}\n  - 操作：{cur[n]['act']}" for n, a, b in changes]
        post(f"【信号提醒】{TODAY} {names}有变化", "\n".join(lines) + "\n\n**全部状态**\n\n" + table(cur), "【信号提醒】")
    else:
        print("信号没有变化，不发提醒")

    if os.environ.get("REPORT") == "1" and not first:
        post(f"【周报】{TODAY} 本周操作", "数据截至各指数最近一个交易日（A股为周四收盘）。创业板轮动、科创板轮动每周五按周四收盘的信号操作（卖出信号出现时当天另发邮件），"
             "红利打分按日操作，A500、沪深300、黄金按倍数每周定投，纳指照常定投；没买完的钱都放红利低波100。比例是每周定投款的分配。\n\n" + table(cur), "【周报】")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
