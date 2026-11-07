import bisect, datetime as dt
import update as U
c,_=U.fetch("创业板50",[("东财",lambda:U.from_eastmoney("0.399673")),("腾讯",lambda:U.from_tencent("sz399673"))])
k,_=U.fetch("科创50",[("东财",lambda:U.from_eastmoney("1.000688")),("腾讯",lambda:U.from_tencent("sh000688"))])
h,_=U.fetch("红利低波100",[("中证",lambda:U.from_csindex("930955"))])
d=sorted(set(c)&set(k)&set(h)); print("区间",d[0],"~",d[-1],len(d),"天")
D=[dt.date.fromisoformat(x) for x in d]; C=[c[x] for x in d]; K=[k[x] for x in d]; H=[h[x] for x in d]
rc=[a/b for a,b in zip(C,H)]; rk=[a/b for a,b in zip(K,H)]
def pct(s,q):
    s=sorted(s);i=(len(s)-1)*q;f=int(i);return s[f]+(s[min(f+1,len(s)-1)]-s[f])*(i-f)
print(f"创业板50÷红利: 最低 {min(rc):.4f} 最高 {max(rc):.4f} 最新 {rc[-1]:.4f}")
print(f"科创50÷红利:   最低 {min(rk):.4f} 最高 {max(rk):.4f} 最新 {rk[-1]:.4f}  P25 {pct(rk,.25):.4f} 中位 {pct(rk,.5):.4f} P75 {pct(rk,.75):.4f}")
# 原阈值 0.16/0.28 在创业板50 十年样本里大约是 P25 / P78 → 科创50 用同样分位定阈值（事后，有前视）
lo_k,hi_k=pct(rk,.245),pct(rk,.782)
print(f"科创50 等分位阈值（事后）: 低 {lo_k:.4f} 高 {hi_k:.4f}；最新比值所在全样本分位 {sum(x<rk[-1] for x in rk)/len(rk)*100:.0f}%")

def sim(G,R,mode,lo=None,hi=None,expand=False,sells=()):
    vg=vh=pool=0.;nav=peak=1.;mdd=0.;prev=0.;cfs=[];lw=None;hist=[];hit=set();z={"l":0,"m":0,"h":0}
    for i,dd in enumerate(D):
        if i:
            vg*=G[i]/G[i-1]*(1+0.004/252); vh*=H[i]/H[i-1]*(1+U.DIV_HL/252); pool*=1+U.CASH_YIELD/252
        cur=vg+vh+pool
        if prev>0: nav*=cur/prev; peak=max(peak,nav); mdd=min(mdd,nav/peak-1)
        bisect.insort(hist,R[i])
        wk=dd.isocalendar()[:2]
        if wk!=lw:
            lw=wk; cfs.append((dd,-1000.))
            if mode=="g": vg+=1000*(1-U.FEE)
            elif mode=="h": vh+=1000*(1-U.FEE)
            elif mode=="mix": vg+=500*(1-U.FEE); vh+=500*(1-U.FEE)
            else:
                pool+=1000
                if expand:
                    if len(hist)<120: L_,H_=-1,9
                    else: L_,H_=pct(hist,.245),pct(hist,.782)
                else: L_,H_=lo,hi
                r=R[i]; zz="l" if r<L_ else ("h" if r>=H_ else "m"); z[zz]+=1
                if zz=="l": vg+=pool*(1-U.FEE); pool=0
                elif zz=="h": vh+=pool*(1-U.FEE); pool=0
                if r<H_: hit.clear()
                for th,fr in sells:
                    t=th if not expand else pct(hist,th)
                    if r>=t and th not in hit and vg>0:
                        a=vg*fr; vg-=a; vh+=a*(1-U.FEE)**2; hit.add(th)
        prev=vg+vh+pool
    f=vg+vh+pool; cfs.append((D[-1],f)); x=U.xirr(cfs)
    return f"年化 {x*100:6.2f}%  回撤 {mdd*100:6.1f}%  期末 {f:>9,.0f}/{-sum(a for _,a in cfs[:-1]):,.0f}  周数 低{z['l']}/中{z['m']}/高{z['h']}"
print("\n== 同一区间每周 1000 元 ==")
print("只定投红利低波100          ",sim(C,rc,"h"))
print("只定投创业板50             ",sim(C,rc,"g"))
print("只定投科创50               ",sim(K,rk,"g"))
print("创业板50+红利 各半          ",sim(C,rc,"mix"))
print("科创50+红利 各半            ",sim(K,rk,"mix"))
print("创业板50轮动 0.16/0.28     ",sim(C,rc,"rot",.16,.28))
print("创业板50轮动+分档卖出       ",sim(C,rc,"rot",.16,.28,sells=[(.32,1/3),(.36,.5),(.40,1.)]))
print(f"科创50轮动 等分位(事后)     ",sim(K,rk,"rot",lo_k,hi_k))
print(f"科创50轮动 滚动分位(无前视) ",sim(K,rk,"rot",expand=True))
for a,b in [(.14,.24),(.15,.26),(.16,.28),(.12,.22),(.18,.30)]:
    print(f"科创50轮动 固定 {a}/{b}       ",sim(K,rk,"rot",a,b))
print("\n== 均值回归检验：比值所在分位 → 之后 26 周 成长指数相对红利的平均表现 ==")
def fwd(G,R,name):
    s=sorted(R);qs=[pct(R,q) for q in (.2,.4,.6,.8)]
    out=[]
    for j in range(5):
        lo_=qs[j-1] if j else -1; hi_=qs[j] if j<4 else 9
        xs=[(G[i+126]/G[i])/(H[i+126]/H[i])-1 for i in range(len(R)-126) if lo_<=R[i]<hi_]
        out.append(f"{['最低20%','20-40%','40-60%','60-80%','最高20%'][j]} {sum(xs)/len(xs)*100:+6.1f}%(赢{sum(x>0 for x in xs)/len(xs)*100:.0f}%)")
    print(name,"  ".join(out))
fwd(C,rc,"创业板50:");fwd(K,rk,"科创50:  ")
import math
def ac(p,st=20):
    r=[math.log(p[i]/p[i-st]) for i in range(st,len(p),st)];m=sum(r)/len(r)
    return sum((r[i]-m)*(r[i-1]-m) for i in range(1,len(r)))/sum((x-m)**2 for x in r)
print(f"\n比值本身 20 日变化自相关（负=均值回归）：创业板50÷红利 {ac(rc):+.2f}  科创50÷红利 {ac(rk):+.2f}")
