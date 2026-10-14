import requests, os, json
from datetime import datetime, timedelta
K=os.environ.get("EVDS_API_KEY"); B="https://evds3.tcmb.gov.tr/igmevdsms-dis/"
print("key", bool(K))
C={"TÜFE":["TP.TUKFIY2025.GENEL"],"YIUFE":["TP.TUFE1YI.T1","TP.URETFIY2025.GENEL","TP.YIUFE2025.GENEL","TP.UFE2025.GENEL"],
 "CARI":["TP.ODEANA6.Q1","TP.ODEMGZS.CARI"],"ISSIZ":["TP.YISGUCU2.G8","TP.TIG08"],"SANAYI":["TP.SANAYREV4.Y1","TP.SANAYREV4.Y2"],
 "KKO":["TP.KKO2.IMA.TOP","TP.KKO.MA"],"RKGE":["TP.GY1.N2.MA","TP.GY1.N2"],"TGE":["TP.TG2.Y01"],"KFE":["TP.KFE.TR","TP.HKFE01"],
 "REZ":["TP.AB.TOPLAM","TP.REZVARLIK.K1","TP.AB.C2"],"YABHISSE":["TP.MKNETHAR.M7","TP.MKNETHAR.M1"],"KONUT":["TP.AKONUTSAT1.TOPLAM"],
 "DISTIC":["TP.IHRACATBEC.9999","TP.ITHALATBEC.9999"],"BUTCE":["TP.KB.GEL001","TP.KB.A01"],"MEVFAIZ":["TP.TRY.MT06"],"KREDIFAIZ":["TP.KTF101"]}
end=datetime.utcnow(); start=end-timedelta(days=500)
for k,codes in C.items():
    for c in codes:
        u=f"{B}series={c}&startDate={start:%d-%m-%Y}&endDate={end:%d-%m-%Y}&type=json"
        try:
            r=requests.get(u,headers={"key":K},timeout=60)
            ok=r.status_code
            try:
                items=r.json().get("items") or []; key=c.replace(".","_")
                vals=[(i.get("Tarih"),i.get(key)) for i in items if i.get(key) not in (None,"")]
                print(k,c,ok,len(vals),vals[-2:])
            except Exception: print(k,c,ok,r.text[:120])
        except Exception as e: print(k,c,"ERR",e)
for code in ["bie_tukfiy2025","bie_pyintbnk"]:
    for u in [f"{B}serieList/type=json&code={code}", f"{B}serieList/code={code}&type=json"]:
        try:
            r=requests.get(u,headers={"key":K},timeout=60); print("SERIELIST",u,r.status_code,r.text[:400])
        except Exception as e: print("ERR",u,e)
