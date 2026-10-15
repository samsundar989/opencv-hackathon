import sys,numpy as np,pandas as pd,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
cams=sys.argv[2:];mode=sys.argv[1]
fig,axs=plt.subplots(len(cams),1,figsize=(12,2.6*len(cams)))
axs=np.atleast_1d(axs)
for ax,cam in zip(axs,cams):
    z=np.load(f'pred/{cam}_{mode}.npz');t=pd.to_datetime(z['t'],unit='us')
    ax.plot(t,z['h'],'k.',ms=3,label='gauge');ax.plot(t,z['pa'],'r.',ms=3,label='thr-map');ax.plot(t,z['pb'],'b.',ms=2,alpha=.5,label='ridge')
    ax.set_title(cam[:50]+' '+mode,fontsize=9);ax.legend(fontsize=7,loc='upper right')
plt.tight_layout();plt.savefig(f'ts_{mode}_{len(cams)}.png',dpi=70)
