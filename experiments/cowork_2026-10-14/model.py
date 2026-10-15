import sys, glob, numpy as np, pandas as pd, cv2
BS=4  # block size on 320x180 -> 80x45 blocks
def feats(imgs):
    n=len(imgs); out=[]
    for im in imgs:
        lab=cv2.cvtColor(im,cv2.COLOR_BGR2LAB).astype(np.float32)
        L=lab[...,0]; L=L-np.median(L)  # global illumination normalise
        gx=cv2.Sobel(lab[...,0],cv2.CV_32F,1,0);gy=cv2.Sobel(lab[...,0],cv2.CV_32F,0,1)
        gm=np.sqrt(gx*gx+gy*gy)
        ch=np.stack([L,lab[...,1],lab[...,2],gm],-1)
        h,w=ch.shape[:2]
        b=ch.reshape(h//BS,BS,w//BS,BS,4)
        mean=b.mean((1,3)); sd=b[...,0].std((1,3))[...,None]
        out.append(np.concatenate([mean,sd],-1).reshape(-1,5))
    return np.array(out,np.float32)  # n,B,5

def fit_thr(X,h,nq=24,minside=8):
    n,B,d=X.shape
    qs=np.unique(np.quantile(h,np.linspace(0.04,0.96,nq)))
    best=np.full(B,-1.0);bthr=np.zeros(B);bw=np.zeros((B,d));bmid=np.zeros((B,d));bsign=np.ones(B)
    for q in qs:
        wet=h>=q; n1=wet.sum(); n0=n-n1
        if n1<minside or n0<minside: continue
        m1=X[wet].mean(0); m0=X[~wet].mean(0)
        v1=X[wet].var(0)+1e-3; v0=X[~wet].var(0)+1e-3
        w=(m1-m0)/(v1+v0)
        mid=(m1+m0)/2
        s=np.einsum('nbd,bd->nb',X-mid,w)
        pred=s>0
        bacc=0.5*(pred[wet].mean(0)+(~pred[~wet]).mean(0))
        upd=bacc>best
        best[upd]=bacc[upd];bthr[upd]=q;bw[upd]=w[upd];bmid[upd]=mid[upd]
    return dict(acc=best,thr=bthr,w=bw,mid=bmid)

def predict_thr(M,X,grid,min_acc=0.85):
    sel=M['acc']>=min_acc
    if sel.sum()<5: return np.full(len(X),np.nan),int(sel.sum())
    w=M['w'][sel];mid=M['mid'][sel];thr=M['thr'][sel];wt=(M['acc'][sel]-0.5)
    s=np.einsum('nbd,bd->nb',X[:,sel]-mid,w)
    wet=s>0
    idx=np.clip(np.searchsorted(grid,thr-1e-9),0,len(grid))  # first grid index with grid>=thr
    out=[]
    for i in range(len(X)):
        hw=np.bincount(idx[wet[i]],wt[wet[i]],minlength=len(grid)+1)[:len(grid)]
        hd=np.bincount(idx[~wet[i]],wt[~wet[i]],minlength=len(grid)+1)[:len(grid)+1]
        sc=np.cumsum(hw)+(hd.sum()-np.cumsum(hd)[:len(grid)])
        m=sc.max(); j=np.where(sc>=m-1e-9)[0]
        out.append(grid[j].mean())
    return np.array(out),int(sel.sum())

def ridge(Xtr,ytr,Xte,lam=1.0):
    A=Xtr.reshape(len(Xtr),-1);Bm=Xte.reshape(len(Xte),-1)
    mu=A.mean(0);sd=A.std(0)+1e-3;A=(A-mu)/sd;Bm=(Bm-mu)/sd
    K=A@A.T/A.shape[1];Kb=Bm@A.T/A.shape[1]
    ym=ytr.mean();alpha=np.linalg.solve(K+lam*0.05*np.eye(len(K)),ytr-ym)
    return Kb@alpha+ym

def evaluate(cam,mode):
    z=np.load(f'cache/{cam}.npz')
    t=pd.to_datetime(z['t'],unit='us',utc=True);h=z['h'];ok=z['ok']
    keep=ok&np.isfinite(h)
    t=t[keep];h=h[keep];X=feats(z['imgs'][keep])
    st=pd.read_csv('/tmp/claude-0/-home-claude/6fecd807-30aa-5eb1-a919-92099c30d93b/scratchpad/exp/stage_hourly.csv',index_col=0,parse_dates=True)[cam]
    p24=st.reindex(t-pd.Timedelta('24h')).values
    day=(t-t[0]).days
    if mode=='fit20':
        m20=day<20; fold=np.where(m20,np.minimum((day*4)//20,3),-1)
        folds=[(m20&(fold!=f), fold==f) for f in range(4)]
    elif mode=='blocked4':
        fold=np.minimum((day*4)//30,3)
        folds=[(fold!=f, fold==f) for f in range(4)]
    else: # leave-one-day-out with 1-day gap each side
        folds=[(np.abs(day-d)>1, day==d) for d in np.unique(day)]
    pa=np.full(len(h),np.nan);pb=np.full(len(h),np.nan);pc=np.full(len(h),np.nan);nsel=[]
    for tr,te in folds:
        if te.sum()==0 or tr.sum()<30: continue
        M=fit_thr(X[tr],h[tr])
        grid=np.arange(h[tr].min(),h[tr].max()+0.005,0.01)
        pa[te],ns=predict_thr(M,X[te],grid);nsel.append(ns)
        pb[te]=ridge(X[tr],h[tr],X[te])
        pc[te]=np.median(h[tr])
    ev=np.abs(h-p24)>=0.25
    sm=pd.Series(pa,index=t).rolling('3h',min_periods=1).median().values
    sb=pd.Series(pb,index=t).rolling('3h',min_periods=1).median().values
    el=h>np.median(h)+0.5
    def bacc(p):
        m=np.isfinite(p)
        if el[m].sum()<3 or (~el[m]).sum()<3: return np.nan
        q=p>np.median(h)+0.5
        return 0.5*(q[m&el].mean()+(~q[m&~el]).mean())
    def mae(p,m=None):
        m=np.isfinite(p)&(np.ones_like(h,bool) if m is None else m)
        return np.nanmean(np.abs(p[m]-h[m])) if m.sum() else np.nan
    r=dict(site=cam[:28],mode=mode,n=len(h),range=h.max()-h.min(),nblk=int(np.median(nsel)) if nsel else 0,
        thr_mae=mae(pa),ridge_mae=mae(pb),const_mae=mae(pc),p24_mae=mae(p24),
        n_ev=int(ev.sum()),thr_ev=mae(pa,ev),ridge_ev=mae(pb,ev),const_ev=mae(pc,ev),p24_ev=mae(p24,ev),
        thr_rho=pd.Series(pa).corr(pd.Series(h),method='spearman'),
        thrS_mae=mae(sm),ridgeS_mae=mae(sb),thrS_ev=mae(sm,ev),ridgeS_ev=mae(sb,ev),
        n_el=int(el.sum()),thr_bacc=bacc(sm),ridge_bacc=bacc(sb),p24_bacc=bacc(p24))
    np.savez(f'pred/{cam}_{mode}.npz',t=z['t'][keep],h=h,pa=pa,pb=pb,sm=sm,sb=sb,pc=pc,p24=p24)
    return r
if __name__=='__main__':
    import os;os.makedirs('pred',exist_ok=True)
    rows=[]
    for f in sorted(glob.glob('cache/*.npz')):
        cam=f.split('/')[-1][:-4]
        for mode in sys.argv[1:]:
            rows.append(evaluate(cam,mode)); print(rows[-1],flush=True)
    pd.DataFrame(rows).round(3).to_csv('results_%s.csv'%'_'.join(sys.argv[1:]),index=False)
