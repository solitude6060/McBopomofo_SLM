# Lexicon coverage of OGDL agency names (2026-08-18)

Source lexicon: `Source/Data/data.txt`  
Name list: `data/opendata/7307_org_names.txt` (16,043 unique `機關名稱` from data.gov.tw dataset 7307)  
Method: substring presence of the whole official name in `data.txt`. This is not a conversion benchmark.

Attribution: 行政院人事行政總處〈行政院所屬中央及地方機關代碼〉, OGDL-Taiwan-1.0, https://data.gov.tw/dataset/7307

## Counts

| Quantity | Value |
|---|---|
| Unique official names | 16,043 |
| Whole name found in `data.txt` | 81 |
| Whole name not found | 15,962 |
| Found / total | 0.0050 |

All 81 hits have name length 3–6. Names of length 7 or more were all absent as whole phrases.

Short missing examples (length ≤ 6): 內政部營建署, 內政部消防署, 內政部警政署, 中央警察大學.

## County names

Official `臺中市` and `臺南市` are absent as whole phrases. The lexicon has `台中市` and `台南市` (`ㄊㄞˊ-ㄓㄨㄥ-ㄕˋ`, `ㄊㄞˊ-ㄋㄢˊ-ㄕˋ`). The other 20 縣市 names using 臺/新/高 etc. that were checked in this pass are present, except that this check used the official 臺 form only for 臺北/臺中/臺南/臺東.

Spotlight (whole phrase in `data.txt`):

| Name | Present |
|---|---|
| 行政院 | yes |
| 行政院人事行政總處 | no |
| 人事行政總處 | no |
| 衛生福利部 | yes |
| 衛生福利部中央健康保險署 | no |
| 中央健康保險署 | no |
| 健保署 | yes |
| 交通部 | yes |
| 臺北市政府 | yes |
| 新北市政府 | no |
| 臺北車站 | no |
| 臺北市立大學 | no |

A later conversion row that expects a long official title as one unigram can still succeed if the engine composes shorter pieces. Mark whole-phrase absence separately from exact-sentence failure.
