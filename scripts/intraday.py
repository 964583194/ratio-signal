"""红利低波100 盘中估算：交易日 13:00~15:00 用实时价格先算出"今天的评分"，给小红书每日图提前用。
写 data/dividend_live.json（和 dividend.json 同格式，另加 live 字段）。晚上收盘数据到了，正式的 dividend.json 会盖过它。
不改任何买卖规则：今天要不要下单看的是前两天涨跌，前一天晚上就定了；这里只是提前预告评分和"明天会不会一起买"。
退出码：0 = 算出来了；3 = 不在时间段 / 不是交易日 / 已有收盘数据（工作流据此跳过后面的步骤）。"""
import datetime as dt
import json
import os
import sys

import sources as S
import dividend as DV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "dividend_live.json")


def bj_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=8)


def quote(secid):
    """东方财富实时价（指数）；拿不到就用日 K 里今天这根还没收盘的线"""
    try:
        j = S.jget(f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fltt=2&fields=f43,f60,f86",
                   "https://quote.eastmoney.com/")["data"]
        p, ts = j.get("f43"), j.get("f86")
        if isinstance(p, (int, float)) and p > 0 and ts:
            return dt.datetime.utcfromtimestamp(ts) + dt.timedelta(hours=8), float(p)
    except Exception as e:  # noqa: BLE001
        print(f"{secid} 实时价失败：{type(e).__name__} {str(e)[:60]}")
    k = S.em_kline(secid, bj_now().strftime("%Y%m%d"))
    d = max(k)
    return dt.datetime.fromisoformat(d + "T15:00:00"), k[d]


def main():
    now = bj_now()
    if os.environ.get("FORCE") != "1" and not (dt.time(13, 0) <= now.time() <= dt.time(15, 0)):
        print(f"现在北京时间 {now:%H:%M}，不在 13:00~15:00，跳过")
        return 3
    today = now.date().isoformat()
    base = {k: S.load_cache(k) for k in ("hl100", "hl100_pe", "hl100_tr", "cn10y", "cyb50")}
    if today in base["hl100"]:
        print("今天已有收盘数据，不用估算")
        return 3
    t_hl, p_hl = quote("2.930955")
    t_c, p_c = quote("0.399673")
    if t_hl.date().isoformat() != today or t_c.date().isoformat() != today:
        print(f"行情时间 {t_hl} / {t_c} 不是今天：今天不是交易日")
        return 3
    aug = {k: dict(v) for k, v in base.items()}
    aug["hl100"][today] = p_hl
    aug["cyb50"][today] = p_c
    pl = max(d for d in base["hl100_pe"] if d in base["hl100"])          # 市盈率按价格涨跌同比例推到今天
    aug["hl100_pe"][today] = base["hl100_pe"][pl] * p_hl / base["hl100"][pl]
    S.get_series = lambda key, min_days=None: (aug[key], "缓存 + 盘中实时价")
    DV.OUT = OUT
    DV.run(aug["cyb50"])
    with open(OUT, encoding="utf-8") as fh:
        d = json.load(fh)
    prev = base["hl100"][max(base["hl100"])]
    d["live"] = {"time": t_hl.strftime("%H:%M"), "date": today, "price": round(p_hl, 2), "chg": round(p_hl / prev - 1, 4)}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    L = d["latest"]
    print(f"盘中估算 {today} {d['live']['time']}：红利低波100 {p_hl}（{d['live']['chg']:+.2%}），评分 {L['score']}（{L['tier']}），明天下单：{L['buy_next']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
