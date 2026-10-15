import re, numpy as np, pandas as pd
A="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXY"
def dec(s):
    cam,body=s.split('|',1)
    vals=[]; i=0
    # leading gaps
    while body[i]=='_': vals.append(np.nan); i+=1
    j=body.index(':',i); last=int(body[i:j]); vals.append(last); i=j+1
    while i<len(body):
        c=body[i]
        if c=='_': vals.append(np.nan); i+=1; continue
        if c=='!':
            j=body.index('!',i+1); d=int(body[i+1:j]); i=j+1
        else:
            d=A.index(c)-30; i+=1
        last+=d; vals.append(last)
    return cam,np.array(vals,float)/100
out={}
for line in open('stage_hourly.txt'):
    line=line.strip()
    if not line: continue
    cam,v=dec(line); out[cam]=v
    print(f"{cam[:40]:40s} n={len(v)} min={np.nanmin(v):.2f} max={np.nanmax(v):.2f} gaps={np.isnan(v).sum()}")
t=pd.date_range('2026-09-14',periods=721,freq='h',tz='UTC')
df=pd.DataFrame({k:v for k,v in out.items() if len(v)==721},index=t)
df.to_csv('stage_hourly.csv')
