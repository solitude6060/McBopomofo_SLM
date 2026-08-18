# Lexicon coverage of selected Taiwan official names (2026-08-17)

Source lexicon: `McBopomofo_SLM/Source/Data/data.txt`  
Method: exact phrase search in that file. This is not a conversion benchmark.

Names are chosen because they appear as fields in OGDL datasets listed in `docs/survey/2026-08-17_taiwan_validation_corpora.md`. Sentences were not copied from those datasets.

| Name | In `data.txt` this pass | Notes |
|---|---|---|
| 南港區 | yes | `ㄋㄢˊ-ㄍㄤˇ-ㄑㄩ` |
| 行政院 | yes | `ㄒㄧㄥˊ-ㄓㄥˋ-ㄩㄢˋ` |
| 人事行政局 | yes | former agency name |
| 人事行政總處 | no | current 行政院人事行政總處 not found as a phrase |
| 健保署 | yes | `ㄐㄧㄢˋ-ㄅㄠˇ-ㄕㄨˇ` |
| 中央健保署 | yes | short form; full 衛生福利部中央健康保險署 not searched as a whole string |
| 板南線 | yes | |
| 新北投 | yes | |
| 象山 | yes | also a common noun / place name outside MRT |
| 展覽館 | yes | `南港展覽館` as a whole phrase not found |
| 樂善 | yes | `樂善里` as a whole phrase not found |
| 台北車站 | no | |
| 臺北車站 | no | |
| 軟體園區 | no | |

A later held-out that expects `人事行政總處` or `臺北車站` as a single unigram will fail for missing candidates, not ranking. Coverage lists should mark those rows as `missing_candidate` before scoring exact sentence match.
