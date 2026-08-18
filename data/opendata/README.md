# Open data extracts for IME validation

License: 政府資料開放授權條款－第1版 (OGDL-Taiwan-1.0), compatible with CC BY 4.0.  
Attribution: 行政院人事行政總處〈行政院所屬中央及地方機關代碼〉, data.gov.tw dataset 7307, https://data.gov.tw/dataset/7307  
Download used this pass: https://www.dgpa.gov.tw/open/code/orglist.csv (BIG5, last-modified 2026-03-02 on the HTTP header).

`7307_orglist.big5.csv` is the original file and includes addresses and phone numbers. Do not copy those fields into IME fixtures.

`7307_org_names.txt` keeps unique `機關名稱` values only (16,043 names). That extract is the IME-usable list.

Do not train an n-gram on this list if the same names are used as held-out coverage.
