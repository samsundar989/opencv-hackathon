import numpy as np,pandas as pd,cv2,model,sys
tiles=[]
for cam in sys.argv[1:]:
    z=np.load(f'cache/{cam}.npz');h=z['h'];keep=z['ok']&np.isfinite(h)
    imgs=z['imgs'][keep];h=h[keep];X=model.feats(imgs)
    M=model.fit_thr(X,h)
    acc=M['acc'].reshape(45,80);thr=M['thr'].reshape(45,80)
    t=pd.to_datetime(z['t'][keep],unit='us',utc=True)
    ref=imgs[np.argmin(np.abs((t-pd.Timestamp('2026-10-01 18:00',tz='UTC')).total_seconds()))]
    lo,hi=np.quantile(h,0.04),np.quantile(h,0.96)
    norm=np.clip((thr-lo)/(hi-lo+1e-6),0,1)
    col=cv2.applyColorMap((255*(1-norm)).astype(np.uint8),cv2.COLORMAP_JET)
    col=cv2.resize(col,(320,180),interpolation=cv2.INTER_NEAREST)
    a=cv2.resize(((acc-0.85)/0.15).clip(0,1).astype(np.float32),(320,180),interpolation=cv2.INTER_NEAREST)[...,None]*0.75
    over=(ref*(1-a)+col*a).astype(np.uint8)
    big=np.hstack([ref,over]);big=cv2.resize(big,(1280,360))
    cv2.putText(big,f'{cam[:40]}  red=wets at low stage {lo:.1f}ft, blue=wets only at {hi:.1f}ft',(8,22),cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,255,255),2)
    tiles.append(big)
cv2.imwrite('floodheight_maps.jpg',np.vstack(tiles),[cv2.IMWRITE_JPEG_QUALITY,80])
