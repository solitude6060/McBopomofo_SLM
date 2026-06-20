#!/usr/bin/env python3
"""
Expand test fixtures to 200+ cases.

Adds 20+ new sentences to each fixture file using the existing
generate_fixtures.py machinery for Bopomofo reading lookup.

Usage:
    python3 expand_fixtures.py --mappings Source/Data/BPMFMappings.txt \
        --data Source/Data/data.txt \
        --gen Tools/generate_fixtures.py
"""

import argparse
import json
import os
import re
import subprocess
import sys


def load_mappings(bpmf_path, data_path):
    """Quick BPMF reading lookup."""
    char_map = {}
    phrase_map = {}
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            reading, value, score_str = parts[0], parts[1], parts[2]
            if reading.startswith("_ctrl_") or reading.startswith("_punctuation_") or reading.startswith("_kana_"):
                continue
            if len(value) != 1 or not (0x4E00 <= ord(value) <= 0x9FFF):
                continue
            try:
                score = float(score_str)
            except ValueError:
                continue
            if value not in char_map or score > char_map[value][1]:
                char_map[value] = (reading, score)
    char_map = {k: v[0] for k, v in char_map.items()}
    with open(bpmf_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            word = parts[0]
            phrase_map[word] = parts[1:]
    return char_map, phrase_map


def sentence_to_readings(sentence, char_map, phrase_map):
    readings = []
    i = 0
    while i < len(sentence):
        char = sentence[i]
        is_cjk = 0x4E00 <= ord(char) <= 0x9FFF
        if not is_cjk:
            start = i
            while i < len(sentence):
                c = sentence[i]
                if 0x4E00 <= ord(c) <= 0x9FFF:
                    break
                i += 1
            readings.append(sentence[start:i])
            continue
        matched = False
        for end in range(min(i + 10, len(sentence)), i, -1):
            word = sentence[i:end]
            if word in phrase_map:
                readings.extend(phrase_map[word])
                i = end
                matched = True
                break
        if matched:
            continue
        if char in char_map:
            readings.append(char_map[char])
        else:
            readings.append(char)
        i += 1
    return readings


def find_protected_spans(sentence):
    spans = []
    i = 0
    while i < len(sentence):
        cp = ord(sentence[i])
        if cp < 0x4E00 or cp > 0x9FFF:
            start = i
            while i < len(sentence):
                cp = ord(sentence[i])
                if 0x4E00 <= cp <= 0x9FFF:
                    break
                i += 1
            spans.append(sentence[start:i])
        else:
            i += 1
    return spans


def generate_fixtures(sentences, char_map, phrase_map, domain, source, start_id):
    fixtures = []
    for idx, entry in enumerate(sentences, start_id):
        if isinstance(entry, str):
            sentence = entry
            expected = sentence
        else:
            sentence = entry["sentence"]
            expected = entry.get("expected", sentence)
        readings = sentence_to_readings(sentence, char_map, phrase_map)
        protected_spans = []
        for reading in readings:
            is_bopomofo = False
            for c in reading:
                if 0x3100 <= ord(c) <= 0x312F or 0x31A0 <= ord(c) <= 0x31BF:
                    is_bopomofo = True
                    break
            if not is_bopomofo and reading.strip():
                flat = find_protected_spans(sentence)
                protected_spans = list(dict.fromkeys(flat))
                break
        fixture = {
            "id": f"tw-{domain}-{idx:03d}",
            "readings": readings,
            "expected": expected,
            "domain": domain,
            "source": source,
            "license": "MIT",
            "redistributable": True,
        }
        if protected_spans:
            fixture["protected_english_spans"] = protected_spans
        fixtures.append(fixture)
    return fixtures


def main():
    parser = argparse.ArgumentParser(description="Expand test fixtures to 200+")
    parser.add_argument("--mappings", required=True, help="Path to BPMFMappings.txt")
    parser.add_argument("--data", required=True, help="Path to data.txt")
    parser.add_argument("--ambiguous", required=True, help="Output path for taiwan_ambiguous.jsonl")
    parser.add_argument("--english", required=True, help="Output path for english_mixed.jsonl")
    parser.add_argument("--specific", required=True, help="Output path for taiwan_specific.jsonl")
    args = parser.parse_args()

    char_map, phrase_map = load_mappings(args.mappings, args.data)
    print(f"Loaded {len(char_map)} chars, {len(phrase_map)} phrases", file=sys.stderr)

    # === New taiwan_ambiguous cases (start after existing 60) ===
    ambiguous = [
        # 員/原/圓
        "他的團隊有十個成員",
        "這個圓圈畫得很圓",
        # 機/基/績
        "公司的業績很好",
        "聖誕節交換禮物",
        # 社/設/涉
        "學校的設備很新",
        "社會福利制度完善",
        # 記/計/繼
        "明天的會議很重要",
        "他繼承了父親的產業",
        # 幾/己/紀
        "自己動手做比較好",
        "紀念品很有意義",
        # 影/應/營
        "公司的營業額成長",
        "我應該去上課",
        # 教/較/叫
        "他比較喜歡游泳",
        "這次交易很成功",
        # 員/圓/元
        "公務員的福利很好",
        "這家餐廳的價錢很合理",
        # 經/京/驚
        "今天的經驗很寶貴",
        "他經營一家小店",
        # 文/問/聞
        "新聞報導很詳細",
        "這篇文章很有意思",
        # 共/工/公
        "公共場所禁止吸煙",
        "工作需要團隊合作",
        # 感/趕/幹
        "他今天很努力",
        "你感覺怎麼樣",
        # 課/克/刻
        "下課後我要去圖書館",
        "立刻開始工作",
        # 標/表/票
        "投票日要到了",
        "這個目標很明確",
        # 材/才/財
        "財務報表要按時繳交",
        "這個材料品質很好",
        # 信/新/心
        "他很有自信",
        "新年快樂恭喜發財",
        # 變/邊/編
        "改變習慣不容易",
        "編寫程式很有趣",
        # 破/頗/婆
        "打破紀錄很開心",
        "隔壁的老婆婆很親切",
        # 第/弟/遞
        "這是第一次來台灣",
        "他的弟弟今年上大學",
        # 法/髮/發
        "他發現了問題所在",
        "理髮店在轉角處",
    ]

    # === New english_mixed cases (start after existing 25) ===
    english_mixed = [
        "請用scp上傳檔案",
        "SSH連線要設金鑰",
        "網站的CDN加速",
        "用Docker-compose部署服務",
        "AWS雲端服務很方便",
        "手機APP更新完成",
        "下載iOS最新版本",
        "Android開發用Kotlin",
        "用Python寫API",
        "RESTful API用JSON格式",
        "node_modules體積很大",
        "這個font-end框架很新",
        "用PostgreSQL存資料",
        "MySQL資料庫要備份",
        "nginx設定要檢查",
        "GitHub Actions跑CI",
        "用Markdown寫文件",
        "YAML設定檔格式要對齊",
        "JWT token過期了",
        "SQL query最佳化很重要",
        "React component很好用",
        "用TypeScript寫比較安全",
        "C++編譯時間很長",
        "Linux kernel更新了",
        "macOS的Homebrew很好用",
    ]

    # === New taiwan_specific cases (start after existing 55) ===
    taiwan_specific = [
        # 超商文化
        "去7-11領包裹很方便",
        "全家咖啡買一送一",
        "用悠遊卡搭捷運",
        "發票中獎了",
        "集點活動開始了",
        # 台灣用語
        "這個便當很便宜",
        "機車要停在格子裡",
        "垃圾車來了快點倒",
        "颱風天要準備泡麵",
        "捷運站出口右轉",
        "高鐵便當很好吃",
        "YouBike站點很密集",
        "UBike二十分鐘內免費",
        # 台灣食物
        "這家雞排很好吃",
        "珍奶少糖去冰",
        "臭豆腐要加泡菜",
        "滷肉飯大碗只要五十元",
        "牛肉麵的湯頭很濃",
        "蚵仔煎要加甜辣醬",
        # 台灣生活
        "健保卡要隨身攜帶",
        "尾牙抽到獎金",
        "春節返鄉人潮多",
        "選舉日要去投票",
        "學弟學妹要畢業了",
        "系學會要辦活動",
        # 網路用語
        "這太扯了吧",
        "你是在哈囉",
        "傻眼貓咪",
        "無言以對",
    ]

    total_new = len(ambiguous) + len(english_mixed) + len(taiwan_specific)
    print(f"Generating {total_new} new fixtures total", file=sys.stderr)

    # Generate each set
    amb_fixtures = generate_fixtures(ambiguous, char_map, phrase_map, "amb", "hand-crafted", start_id=61)
    en_mix_fixtures = generate_fixtures(english_mixed, char_map, phrase_map, "mix", "hand-crafted", start_id=26)
    # Fix ID prefix: existing uses en-mix-*, generator uses tw-mix-*
    for fx in en_mix_fixtures:
        fx["id"] = fx["id"].replace("tw-mix-", "en-mix-", 1)
    tw_fixtures = generate_fixtures(taiwan_specific, char_map, phrase_map, "taiwan_specific", "generated", start_id=56)

    # Write output files
    # For ambiguous: merge with existing if it exists
    out_path = args.ambiguous
    existing_amb = []
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_amb.append(json.loads(line))
    all_amb = existing_amb + amb_fixtures
    with open(out_path, "w", encoding="utf-8") as f:
        for fx in all_amb:
            f.write(json.dumps(fx, ensure_ascii=False) + "\n")
    print(f"{out_path}: {len(existing_amb)} + {len(amb_fixtures)} = {len(all_amb)}", file=sys.stderr)

    # english_mixed
    out_path = args.english
    existing_en = []
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_en.append(json.loads(line))
    all_en = existing_en + en_mix_fixtures
    with open(out_path, "w", encoding="utf-8") as f:
        for fx in all_en:
            f.write(json.dumps(fx, ensure_ascii=False) + "\n")
    print(f"{out_path}: {len(existing_en)} + {len(en_mix_fixtures)} = {len(all_en)}", file=sys.stderr)

    # taiwan_specific
    out_path = args.specific
    existing_tw = []
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_tw.append(json.loads(line))
    all_tw = existing_tw + tw_fixtures
    with open(out_path, "w", encoding="utf-8") as f:
        for fx in all_tw:
            f.write(json.dumps(fx, ensure_ascii=False) + "\n")
    print(f"{out_path}: {len(existing_tw)} + {len(tw_fixtures)} = {len(all_tw)}", file=sys.stderr)


if __name__ == "__main__":
    main()
