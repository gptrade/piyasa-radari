import os, json, requests
key = os.environ.get("EVDS_API_KEY") or ""
u = "https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.GENENDEKS.T1&startDate=01-01-2023&endDate=07-10-2026&type=json&frequency=5"
r = requests.get(u, headers={"key": key}, timeout=60).json()
print(json.dumps({x["Tarih"]: x.get("TP_GENENDEKS_T1") for x in r["items"]}))
