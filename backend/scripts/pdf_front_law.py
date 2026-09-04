"""One-off: extract Table 1 (rectangular section, plane symmetry) of Martin & Moyce 1952."""
import re

from pypdf import PdfReader

r = PdfReader(r"C:\Users\Arpit Singh\AppData\Local\Temp\martin_moyce_1952.pdf")
txt = ""
for p in r.pages:
    txt += p.extract_text() + "\n"

i = txt.find("TABLE 1")
print(txt[i : i + 1800])
