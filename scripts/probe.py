import json, urllib.request, urllib.parse
H={"User-Agent":"Mozilla/5.0 Chrome/124","Accept":"application/json,*/*"}
def get(u,ref):
    r=urllib.request.Request(u,headers={**H,"Referer":ref})
    return urllib.request.urlopen(r,timeout=25).read()
def p(name,f):
    try: print("##",name,"\n",f())
    except Exception as e: print("##",name,"ERROR",e)
def cs(code):
    j=json.loads(get(f"https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode={code}&startDate=20160101&endDate=20261231","https://www.csindex.com.cn/"))
    d=j.get("data") or []
    return f"rows={len(d)} first={d[:1]} last={d[-1:]}"
p("csindex 930955",lambda:cs("930955"))
p("csindex H20955",lambda:cs("H20955"))
def ind():
    b=get("https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/930955indicator.xls","https://www.csindex.com.cn/")
    return f"bytes={len(b)} head={b[:8]!r}"
p("csindex indicator xls",ind)
def cgb():
    q=urllib.parse.urlencode({"reportName":"RPTA_WEB_TREASURYYIELD","columns":"ALL","sortColumns":"SOLAR_DATE","sortTypes":"-1","pageNumber":"1","pageSize":"3","source":"WEB","client":"WEB"})
    j=json.loads(get("https://datacenter.eastmoney.com/api/data/v1/get?"+q,"https://data.eastmoney.com/"))
    r=j.get("result") or {}
    return f"pages={r.get('pages')} count={r.get('count')} sample={(r.get('data') or [])[:2]}"
p("eastmoney CGB",cgb)
def em(secid):
    q=urllib.parse.urlencode({"secid":secid,"fields1":"f1,f2,f3","fields2":"f51,f53","klt":"101","fqt":"0","beg":"20140101","end":"20500101","ut":"fa5fd1943c7b386f172d6893dbfba10b"})
    j=json.loads(get("https://push2his.eastmoney.com/api/qt/stock/kline/get?"+q,"https://quote.eastmoney.com/"))
    k=(j.get("data") or {}).get("klines") or []
    return f"n={len(k)} first={k[:1]} last={k[-1:]}"
p("eastmoney 2.H20955",lambda:em("2.H20955"))
p("eastmoney 0.399006",lambda:em("0.399006"))
