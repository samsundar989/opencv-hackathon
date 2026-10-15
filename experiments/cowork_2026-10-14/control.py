# Confound control: ridge using only blocks that do NOT behave like inundation pixels (low threshold-map separability)
import numpy as np,pandas as pd,glob,model
rows=[]
for f in sorted(glob.glob('cache/*.npz')):
    cam=f.split('/')[-1][:-4]; z=np.load(f)
    t=pd.to_datetime(z['t'],unit='us',utc=True);h=z['h'];keep=z['ok']&np.isfinite(h)
    t=t[keep];h=h[keep];X=model.feats(z['imgs'][keep]);day=(t-t[0]).days
    m20=day<20;fold=np.where(m20,np.minimum((day*4)//20,3),-1)
    res={'all':[], 'nonwater':[], 'water':[], 'top25':[]}
    P={k:np.full(len(h),np.nan) for k in res}
    for fo in range(4):
        tr=m20&(fold!=fo);te=fold==fo
        M=model.fit_thr(X[tr],h[tr]); acc=M['acc']
        nb=X.shape[1]; rowsidx=np.arange(nb)//80
        sel={'all':np.ones(nb,bool),'nonwater':acc<0.7,'water':acc>=0.85,'top25':rowsidx<11}
        for k,s in sel.items():
            if s.sum()<20: continue
            P[k][te]=model.ridge(X[tr][:,s],h[tr],X[te][:,s])
    r={'site':cam[:16]}
    for k in P:
        p=pd.Series(P[k],index=t).rolling('3h',min_periods=1).median().values
        mm=np.isfinite(p); r[k]=np.mean(np.abs(p[mm]-h[mm])) if mm.sum() else np.nan
    rows.append(r);print(r,flush=True)
pd.DataFrame(rows).round(3).to_csv('control.csv',index=False)
