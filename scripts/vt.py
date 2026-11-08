import datetime as dt, value as V, update as U, dividend as Dv
from value import *
# ---- A500
px_raw=em_kline("1.000510","20050101"); pe_raw=csindex_pe("000300"); cgb=treasury("EMM00166466")
dates=sorted(d for d in px_raw if d>=min(pe_raw)); pk,ck=sorted(pe_raw),sorted(cgb)
px=[px_raw[d] for d in dates]; pe=[on_or_before(pe_raw,pk,d) for d in dates]; y10=[on_or_before(cgb,ck,d) for d in dates]
erp=[None if p is None or y is None else 100/p-y for p,y in zip(pe,y10)]
Dv.WARMUP=750
pp=expanding_share(pe,"lt"); ep=expanding_share(erp,"lt")
cheap=[None if a is None or b is None else 50*(1-a)+50*b for a,b in zip(pp,ep)]
m250=ma(px,250); below=below_flags(px,m250)
i0=next(i for i,c in enumerate(cheap) if c is not None and m250[i])
D=[dt.date.fromisoformat(x) for x in dates[i0:]]; P=px[i0:]; C=cheap[i0:]; B=below[i0:]
print("A500 回测起点",dates[i0])
print("plain",backtest(D,P,.025))
schemes={"原 2/1.5/1/0.5/0":[2,1.5,1,.5,0],"3/2/1/0.5/0":[3,2,1,.5,0],"2/1.5/1/0.6/0.3":[2,1.5,1,.6,.3],"3/2/1/0.6/0.3":[3,2,1,.6,.3],"2.5/1.5/1/0.7/0.5":[2.5,1.5,1,.7,.5],"4/2/1/0.5/0.25":[4,2,1,.5,.25]}
for nm,ms in schemes.items():
    f=lambda c:ms[0] if c>=80 else ms[1] if c>=60 else ms[2] if c>=40 else ms[3] if c>=20 else ms[4]
    print(nm,backtest(D,P,.025,[f(c) for c in C]))
fwd=forward(P,[(z,(lambda i,lo=lo,hi=hi:lo<=C[i]<hi)) for z,lo,hi in [("≥80",80,101),("60-80",60,80),("40-60",40,60),("20-40",20,40),("<20",-1,20)]])
for r in fwd:print(r)
# ---- NDX
raw=U.from_tencent("us.NDX"); dts=sorted(raw); px=[raw[d] for d in dts]
pk_,dd=0,[]
for v in px: pk_=max(pk_,v); dd.append(1-v/pk_)
m=ma(px,250); bl=below_flags(px,m)
D=[dt.date.fromisoformat(x) for x in dts[250:]]; P=px[250:]; DD=dd[250:]; B=bl[250:]
print("NDX plain",backtest(D,P,.007))
for nm,ms in {"0.8/1.5/2/3":[.8,1.5,2,3],"0.7/1.5/2/3":[.7,1.5,2,3],"0.6/1.5/2.5/4":[.6,1.5,2.5,4],"0.5/2/3/4":[.5,2,3,4],"0.8/1.2/1.5/2":[.8,1.2,1.5,2]}.items():
    f=lambda x:ms[3] if x>=.3 else ms[2] if x>=.2 else ms[1] if x>=.1 else ms[0]
    r=backtest(D,P,.007,[f(x) for x in DD]); r2=backtest(D,P,.007,[min(f(x),1) if b else f(x) for x,b in zip(DD,B)])
    print(nm,r,"| +年线暂停加码",r2)
