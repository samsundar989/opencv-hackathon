# Register hourly daylight frames to a per-site reference; cache warped 320x180 Lab + metadata.
import sys, os, glob, re, numpy as np, pandas as pd, cv2, time
EXP='/tmp/claude-0/-home-claude/6fecd807-30aa-5eb1-a919-92099c30d93b/scratchpad/exp'
st=pd.read_csv(f'{EXP}/stage_hourly.csv',index_col=0,parse_dates=True)
cv2.setNumThreads(1)
W,H=320,180
def load(p):
    im=cv2.imread(p); 
    if im is None: return None
    return cv2.resize(im,(1280,720),interpolation=cv2.INTER_AREA)
def run(cam):
    out=f'cache/{cam}.npz'
    if os.path.exists(out): return
    fs=sorted(glob.glob(f'{EXP}/data/raw/720/{cam}/*.jpg'))
    rows=[]
    for p in fs:
        m=re.search(r'___(\d{4}-\d\d-\d\dT\d\d)-(\d\d)-(\d\d)Z',p)
        ts=pd.Timestamp(m.group(1)+':'+m.group(2)+':'+m.group(3),tz='UTC')
        hr=ts.round('h')
        if abs((ts-hr).total_seconds())>600: continue
        rows.append((hr,p))
    df=pd.DataFrame(rows,columns=['t','p']).drop_duplicates('t').set_index('t')
    df=df[df.index.isin(st.index)]
    # daylight filter on small thumbnails
    keep=[]
    for t,p in df.p.items():
        im=cv2.imread(p,cv2.IMREAD_REDUCED_COLOR_4)
        if im is None: continue
        hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
        if hsv[...,2].mean()>60 and hsv[...,1].mean()>18: keep.append(t)
    df=df.loc[keep]
    # reference: daylight frame closest to 2026-10-01 18:00Z
    tref=pd.Timestamp('2026-10-01 18:00',tz='UTC')
    ref_t=df.index[np.argmin(np.abs((df.index-tref).total_seconds()))]
    sift=cv2.SIFT_create(4000)
    ref=load(df.p[ref_t]); rg=cv2.cvtColor(ref,cv2.COLOR_BGR2GRAY)
    kr,dr=sift.detectAndCompute(cv2.resize(rg,(960,540)),None)
    bf=cv2.BFMatcher(cv2.NORM_L2)
    S=np.array([[960/1280,0,0],[0,540/720,0],[0,0,1]])
    imgs=[];ts=[];ok=[];ninl=[]
    for t,p in df.p.items():
        im=load(p)
        if im is None: continue
        g=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        k,d=sift.detectAndCompute(cv2.resize(g,(960,540)),None)
        Hm=None;ni=0
        if d is not None and len(k)>20:
            mm=bf.knnMatch(d,dr,k=2)
            good=[a for a,b in (x for x in mm if len(x)==2) if a.distance<0.8*b.distance]
            if len(good)>=20:
                src=np.float32([k[a.queryIdx].pt for a in good]); dst=np.float32([kr[a.trainIdx].pt for a in good])
                Hs,mask=cv2.findHomography(src,dst,cv2.USAC_MAGSAC,3.0)
                if Hs is not None:
                    ni=int(mask.sum())
                    if ni>=25 and ni/len(good)>0.15: Hm=np.linalg.inv(S)@Hs@S
        ninl.append(ni); ok.append(Hm is not None)
        if Hm is None: Hm=np.eye(3)
        wimg=cv2.warpPerspective(im,Hm,(1280,720),flags=cv2.INTER_AREA,borderMode=cv2.BORDER_REPLICATE)
        small=cv2.resize(wimg,(W,H),interpolation=cv2.INTER_AREA)
        imgs.append(small); ts.append(t)
    ts=pd.DatetimeIndex(ts)
    np.savez_compressed(out,imgs=np.array(imgs),t=ts.astype('int64').values,ok=np.array(ok),ninl=np.array(ninl),h=st.loc[ts,cam].values,ref_t=str(ref_t))
    print(cam,len(ts),'reg_ok=%.2f'%np.mean(ok),flush=True)
os.makedirs('cache',exist_ok=True)
for cam in sys.argv[1:]:
    t0=time.time(); run(cam); print(' %.0fs'%(time.time()-t0),flush=True)
