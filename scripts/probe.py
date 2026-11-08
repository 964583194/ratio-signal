import json, urllib.parse
import update as U, dividend as Dv
def t(name,f):
    try: print("##",name,f())
    except Exception as e: print("##",name,"ERROR",repr(e)[:200])
def cs(code):
    d=Dv.csindex(code); k=sorted(d); pe=[d[x][1] for x in k if d[x][1]]
    return f"days={len(k)} first={k[0]} {d[k[0]]} last={k[-1]} {d[k[-1]]} pe_days={len(pe)} pe_min={min(pe) if pe else None} pe_max={max(pe) if pe else None}"
t("csindex 000510 A500",lambda:cs("000510"))
t("csindex 000300",lambda:cs("000300"))
def em(secid,beg="19900101"):
    q=urllib.parse.urlencode({"secid":secid,"fields1":"f1,f2,f3","fields2":"f51,f53","klt":"101","fqt":"0","beg":beg,"end":"20500101","ut":"fa5fd1943c7b386f172d6893dbfba10b"})
    j=U.get_json("https://push2his.eastmoney.com/api/qt/stock/kline/get?"+q,"https://quote.eastmoney.com/")
    k=(j.get("data") or {}).get("klines") or []
    return f"n={len(k)} first={k[:1]} last={k[-2:]} name={(j.get('data') or {}).get('name')}"
for s in ["100.NDX","100.NDX100","100.VIX","1.513100","0.159941","1.000510","2.000510"]:
    t("em "+s,lambda s=s:em(s))
t("tencent usNDX",lambda:(lambda d:f"n={len(d)} last={sorted(d)[-1:]}")(U.from_tencent("us.NDX")))
def tsy():
    q=urllib.parse.urlencode({"reportName":"RPTA_WEB_TREASURYYIELD","columns":"ALL","sortColumns":"SOLAR_DATE","sortTypes":"-1","pageNumber":"1","pageSize":"2","source":"WEB","client":"WEB"})
    j=U.get_json("https://datacenter.eastmoney.com/api/data/v1/get?"+q,"https://data.eastmoney.com/")
    return (j.get("result") or {}).get("data")
t("treasury cols",tsy)
def lsjz(code):
    u=f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=5"
    j=U.get_json(u,"https://fundf10.eastmoney.com/")
    return [(r["FSRQ"],r["DWJZ"]) for r in (j.get("Data") or {}).get("LSJZList") or []]
t("nav 513100",lambda:lsjz("513100"))
t("nav 159941",lambda:lsjz("159941"))
