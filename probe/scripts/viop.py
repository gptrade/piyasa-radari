import io, zipfile, requests, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "xlrd"])
import xlrd
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
r = requests.get("https://borsaistanbul.com/files/datafilepaths_viop.zip", headers=UA, timeout=40)
z = zipfile.ZipFile(io.BytesIO(r.content))
b = xlrd.open_workbook(file_contents=z.read(z.namelist()[0]))
for sh in b.sheets():
    print("== sheet", sh.name, sh.nrows)
    for i in range(sh.nrows):
        print(" | ".join(str(c.value) for c in sh.row(i)))
