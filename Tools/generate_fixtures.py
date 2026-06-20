#!/usr/bin/env python3
"""
Generate evaluator test fixtures from Chinese sentences.

Loads BPMFMappings.txt to build character→reading and phrase→reading maps,
then converts a list of Chinese sentences into JSONL fixtures.

Usage:
    python3 generate_fixtures.py --mappings ../Source/Data/BPMFMappings.txt \\
        --fixtures ../Tests/fixtures/contextual_bopomofo/taiwan_specific.jsonl
"""

import argparse
import json
import sys
import os


def load_mappings(bpmf_path, data_path):
    """Load BPMFMappings.txt (multi-char phrases) + data.txt (single chars).

    Returns:
        char_map: {char: most_common_reading}
        phrase_map: {phrase: [reading1, reading2, ...]}
    """
    char_map = {}
    phrase_map = {}
    total = 0

    # Load single characters from data.txt (reading value score)
    # Pick the highest-scored (most common) reading for each char
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            reading, value, score_str = parts[0], parts[1], parts[2]
            # Skip control/punctuation/kana entries
            if reading.startswith("_ctrl_") or reading.startswith("_punctuation_") or reading.startswith("_kana_"):
                continue
            # Only single CJK characters
            if len(value) != 1 or not (0x4E00 <= ord(value) <= 0x9FFF):
                continue
            try:
                score = float(score_str)
            except ValueError:
                continue
            # Keep the highest-score reading for each character
            if value not in char_map or score > char_map[value][1]:
                char_map[value] = (reading, score)
            total += 1

    # Convert to simple char→reading map
    char_map = {k: v[0] for k, v in char_map.items()}

    # Load multi-character phrases from BPMFMappings.txt
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

    print(f"Loaded {total} char entries, {len(char_map)} unique chars, "
          f"{len(phrase_map)} phrases", file=sys.stderr)
    return char_map, phrase_map


def sentence_to_readings(sentence, char_map, phrase_map):
    """Convert a Chinese sentence to a list of Bopomofo readings.

    Uses longest-match from phrase_map first, falls back to char-level.
    Non-CJK characters are grouped into contiguous spans (e.g., "CP" → ["CP"]).
    Returns list of reading strings (one per syllable/protected-span position).
    """
    readings = []
    i = 0
    while i < len(sentence):
        char = sentence[i]
        is_cjk = 0x4E00 <= ord(char) <= 0x9FFF

        if not is_cjk:
            # Group consecutive non-CJK characters
            start = i
            while i < len(sentence):
                c = sentence[i]
                if 0x4E00 <= ord(c) <= 0x9FFF:
                    break
                i += 1
            readings.append(sentence[start:i])
            continue

        # Try longest match from phrase_map (multi-char words)
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

        # Fall back to character level
        if char in char_map:
            readings.append(char_map[char])
        else:
            readings.append(char)
        i += 1

    return readings


def find_protected_spans(sentence):
    """Find non-Chinese spans in the sentence for protected_english_spans."""
    spans = []
    i = 0
    while i < len(sentence):
        cp = ord(sentence[i])
        if cp < 0x4E00 or cp > 0x9FFF:
            # Non-CJK character
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


def generate_fixtures(sentences, char_map, phrase_map, domain="taiwan_specific", source="manual"):
    """Generate evaluator JSONL fixtures from a list of sentences."""
    fixtures = []
    for idx, entry in enumerate(sentences, 1):
        if isinstance(entry, str):
            sentence = entry
            expected = sentence
        else:
            sentence = entry["sentence"]
            expected = entry.get("expected", sentence)

        readings = sentence_to_readings(sentence, char_map, phrase_map)

        # Check for non-Bopomofo tokens that need protected spans
        protected_spans = []
        for reading in readings:
            if not reading or not reading[0].startswith('\u3100') and not any(
                0x3100 <= ord(c) <= 0x312F or 0x31A0 <= ord(c) <= 0x31BF
                for c in reading
            ):
                protected_spans.append(find_protected_spans(sentence))
                break

        fixture = {
            "id": f"tw-{domain}-{idx:03d}",
            "readings": readings,
            "expected": expected,
            "domain": domain,
            "source": source,
        }
        if protected_spans:
            # Flatten and deduplicate
            flat = []
            for s in protected_spans:
                flat.extend(s)
            fixture["protected_english_spans"] = list(set(flat))
        fixtures.append(fixture)
    return fixtures


def write_fixtures(fixtures, path):
    """Write fixtures to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for fx in fixtures:
            f.write(json.dumps(fx, ensure_ascii=False) + "\n")
    print(f"Wrote {len(fixtures)} fixtures to {path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Generate evaluator test fixtures")
    parser.add_argument("--mappings", required=True, help="Path to BPMFMappings.txt")
    parser.add_argument("--data", required=True, help="Path to data.txt (for single-char readings)")
    parser.add_argument("--fixtures", required=True, help="Output JSONL path")
    parser.add_argument("--domain", default="taiwan_specific", help="Domain tag for fixtures")
    args = parser.parse_args()

    char_map, phrase_map = load_mappings(args.mappings, args.data)

    # Taiwan-specific test sentences
    # Format: plain string or {"sentence": "...", "expected": "..."} for ambiguous cases
    sentences = [
        # === Taiwan-specific vocabulary (日常用語) ===
        "我買了一個便當",
        "他騎機車上班",
        "這家超商有賣咖啡",
        "搭捷運比較方便",
        "你真的很白目欸",
        "柯文哲是阿北",
        "這件衣服CP值很高",
        "他是個魯蛇",
        "這家店遇到奧客",
        "我昨天落枕了",
        "那個影片很ㄎㄧㄤ",
        "他是個雷包",
        "今天很雷",
        "你是在哈囉？",
        "這樣很母湯喔",
        "我快被搞到牙起來",
        "這間店很chill",
        "今天要來開箱新產品",

        # === Taiwan vs Mainland differences (台陸差異) ===
        "我用滑鼠操作電腦",
        "請幫我列印這份文件",
        "我搭計程車去機場",
        "這支手機效能很好",
        "商店街有許多文具",
        "請使用雷射印表機",
        "這條高速公路的交流道",
        "便利商店在轉角",
        "我今天吃馬鈴薯",

        # === Taiwan food culture (台灣飲食) ===
        "我要一份蛋餅和豆漿",
        "這家滷肉飯很好吃",
        "夜市有賣珍珠奶茶",
        "臭豆腐配泡菜最對味",
        "我要一碗牛肉麵",
        "下午茶吃蛋糕配咖啡",
        "刈包搭配酸菜",
        "蚵仔煎要加甜辣醬",
        "來碗豬血糕",
        "車輪餅要奶油口味",

        # === Taiwan-specific homophone challenges ===
        "這部電影很感人",
        "你登錄帳號了嗎",
        "去便利商店繳費",
        "我在超商取貨",
        "他用悠遊卡付錢",
        "icash可以搭捷運",
        "YouBike站點很多",
        "高鐵到左營站",
        "台鐵便當很有名",
        "年終獎金變少了",
        "這件事情很兩難",
        "你怎麼又在耍白痴",
        "系主任今天的臉色不太好",
        "期中考要認真準備",
        "我抽到替代役",
        "教召通知來了",
        "學測成績出來了",
        "分科測驗要加油",
    ]

    fixtures = generate_fixtures(sentences, char_map, phrase_map, domain=args.domain)
    write_fixtures(fixtures, args.fixtures)

    # Print summary
    total_readings = sum(len(f["readings"]) for f in fixtures)
    print(f"Total: {len(fixtures)} sentences, {total_readings} readings", file=sys.stderr)


if __name__ == "__main__":
    main()
