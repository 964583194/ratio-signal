import math, datetime as dt
import update as U
c,_=U.fetch("创业板50",[("东财",lambda:U.from_eastmoney("0.399673")),("腾讯",lambda:U.from_tencent("sz399673"))])
k,_=U.fetch("科创50",[("东财",lambda:U.from_eastmoney("1.000688")),("腾讯",lambda:U.from_tencent("sh000688"))])
d=sorted(set(c)&set(k)); print("区间",d[0],"~",d[-1],len(d),"天")
C=[c[x] for x in d]; K=[k[x] for x in d]
def corr(a,b):
    ma,mb=sum(a)/len(a),sum(b)/len(b)
    cov=sum((x-ma)*(y-mb) for x,y in zip(a,b)); va=sum((x-ma)**2 for x in a); vb=sum((y-mb)**2 for y in b)
    return cov/math.sqrt(va*vb)
def rets(p,step): return [p[i]/p[i-step]-1 for i in range(step,len(p),step)]
for nm,st in [("日",1),("周(5日)",5),("月(20日)",20)]:
    print(f"{nm}收益相关系数 {corr(rets(C,st),rets(K,st)):.2f}")
rc,rk=rets(C,1),rets(K,1)
print(f"年化波动 创业板50 {math.sqrt(252)*math.sqrt(sum(x*x for x in rc)/len(rc))*100:.1f}%  科创50 {math.sqrt(252)*math.sqrt(sum(x*x for x in rk)/len(rk))*100:.1f}%")
same=sum((a>0)==(b>0) for a,b in zip(rc,rk))/len(rc); print(f"同涨同跌天数占比 {same*100:.0f}%")
print("年度涨跌：")
yrs=sorted(set(x[:4] for x in d))
for y in yrs:
    idx=[i for i,x in enumerate(d) if x[:4]==y]; i0=max(idx[0]-1,0); i1=idx[-1]
    print(f"  {y}: 创业板50 {(C[i1]/C[i0]-1)*100:+6.1f}%   科创50 {(K[i1]/K[i0]-1)*100:+6.1f}%   滚动60日相关均值 {sum(corr(rc[j-60:j],rk[j-60:j]) for j in range(max(60,idx[0]),idx[-1]+1))/max(1,len(range(max(60,idx[0]),idx[-1]+1))):.2f}")
def mdd(p):
    pk=p[0];m=0;at=None
    for i,x in enumerate(p):
        pk=max(pk,x)
        if x/pk-1<m:m=x/pk-1;at=d[i]
    return m,at
print("最大回撤 创业板50 %.1f%% (%s)  科创50 %.1f%% (%s)"%(mdd(C)[0]*100,mdd(C)[1],mdd(K)[0]*100,mdd(K)[1]))
r=[a/b for a,b in zip(C,K)]
print(f"创业板50÷科创50 比值：起点 {r[0]:.3f} 最新 {r[-1]:.3f} 最低 {min(r):.3f} 最高 {max(r):.3f}")
for y in yrs[-2:]:
    for m in range(1,13):
        idx=[i for i,x in enumerate(d) if x[:7]==f"{y}-{m:02d}"]
        if not idx: continue
        i0=max(idx[0]-1,0);i1=idx[-1]
        print(f"  {y}-{m:02d}: 创业板50 {(C[i1]/C[i0]-1)*100:+5.1f}%  科创50 {(K[i1]/K[i0]-1)*100:+5.1f}%")
