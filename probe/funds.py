"""探测：持有基金名称 → 代码；取复权净值（按日增长率连乘）"""
import json, re, time, urllib.request
import akshare as ak
Q = ["南方亚太精选ETF联接","银华中小盘混合A","财通成长优选混合C","英大策略优选C","华泰柏瑞中韩半导体","富国创业板人工智能",
 "永赢先进制造智选混合","国泰中证机床ETF发起联接","天弘中证科创创业50","永赢先锋半导体智选混合","摩根日本精选股票","华夏节能环保股票C",
 "永赢数字经济智选混合","嘉实上证科创板芯片","浦银安盛全球智能科技","东方阿尔法科技甄选","嘉实全球产业升级股票","嘉实中证稀土产业ETF联接",
 "德邦稳盈增长灵活配置","嘉实美国成长股票人民币","易方达中证A500ETF联接","天弘中证电网设备特高压","上银先进制造混合发起","平安新能源精选混合",
 "国泰中证畜牧养殖ETF联接","华泰柏瑞中证全指电力公用事业","方正富邦中证保险C","广发中证稀有金属ETF联接","汇添富纳斯达克100ETF联接","建信纳斯达克100指数",
 "广发国证半导体材料设备","建信新兴市场混合","方正富邦致盛混合C","鹏华国证粮食产业ETF联接","广发中证军工ETF联接","平安中证卫星产业指数",
 "易方达中证软件服务ETF联接C","富国中证细分化工产业","易方达恒生科技ETF联接","兴业中证港股通互联网","华安黄金ETF联接C","广发上海金ETF联接C",
 "银华国证港股通创新药","博时中债7-10年政策性金融债","华宝致远混合(QDII)C","华夏全球科技先锋混合","易方达全球成长精选"]
df = ak.fund_name_em()
rows = [(str(r["基金代码"]), str(r["基金简称"]), str(r["基金类型"])) for _, r in df.iterrows()]
print("全部基金", len(rows))
def norm(s): return re.sub(r"[()（）\s]|发起式|发起", "", s.replace("人民币", "").replace("股票", "").replace("指数", ""))
def g(s): return {s[i:i+2] for i in range(len(s)-1)}
def score(q, name):
    A, B = g(norm(q)), g(norm(name))
    if not A or not B: return 0
    sc = len(A & B) / len(A) - 0.01 * len(B - A)
    if q.endswith("C") and not name.endswith("C"): sc -= .15
    if q.endswith("A") and not name.endswith("A"): sc -= .15
    return sc
res = {}
for q in Q:
    cand = sorted(rows, key=lambda r: -score(q, r[1]))[:4]
    res[q] = [[c, n, t, round(score(q, n), 2)] for c, n, t in cand]
    print(q, "→", res[q][0], "| 备选", res[q][1:3])
def nav(code):
    req = urllib.request.Request(f"https://fund.eastmoney.com/pingzhongdata/{code}.js?v={int(time.time())}", headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"})
    t = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    L = json.loads(re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", t).group(1))
    out, v = [], 1.0
    for i, p in enumerate(L):
        er = p.get("equityReturn")
        if i and isinstance(er, (int, float)): v *= 1 + er / 100
        out.append([time.strftime("%Y-%m-%d", time.gmtime(p["x"] / 1000 + 8 * 3600)), round(v, 6)])
    return out
navs = {}
for q in Q:
    for c, n, t, sc in res[q][:2]:     # 前两个候选都取，方便人工确认 A/C
        if c in navs: continue
        try:
            navs[c] = nav(c); print("净值", c, n, len(navs[c]), navs[c][0][0], navs[c][-1])
        except Exception as e:
            print("净值失败", c, e)
s = json.dumps({"match": res, "nav": navs}, ensure_ascii=False, separators=(",", ":"))
for i in range(0, len(s), 1500):
    print(f"CHUNK{i // 1500:05d}:" + s[i:i + 1500])
print("CHUNKEND")
