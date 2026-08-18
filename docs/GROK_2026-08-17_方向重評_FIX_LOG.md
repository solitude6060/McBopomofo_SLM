# Grok 2026-08-17 方向重評修正紀錄

最後更新：2026-08-17T23:19:03+08:00

對應審查：`GROK_2026-08-17_方向重評.md`

| ID | 處理 | 作法 |
|---|---|---|
| R1 | 已修 | octagram 改為 BSD-3-Clause。GPL 不相容改寫到 Squirrel / Weasel / rime-ice。仍不複製 octagram 原始碼。 |
| R2 | 已修 | 規劃索引與方向重評改為雙分支：成功標準未確認前不開始 fixture／UOM／n-gram。A–C 先量測現況 UOM；D 先做一次公開 n-gram。 |
| R3 | 已修 | 第 0 步只凍結規則寫入。訓練語料 audit 移到 D 分支的 n-gram 步。半衰期／新鍵／持久化移到現況量測之後。 |
| R4 | 已修 | Zhang 2019 People's Daily top-1 改為 71.3，並標 Table 3。 |

未改引擎程式。未 commit。
