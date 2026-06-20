#!/usr/bin/env python3
"""
Bigram trainer for McBopomofo dictionary data.

Reads BPMFMappings.txt and data.txt, counts character bigram frequencies,
and outputs a BIGR-format binary model plus a manifest JSON file.
"""

import argparse
import json
import struct
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Tuple
import hashlib


def parse_bpmf_mappings(file_path: Path) -> List[str]:
    """Parse BPMFMappings.txt file and extract phrases.
    
    Format: phrase bpmf1 bpmf2 ... (space-separated)
    Example: "一一 ㄧ ㄧ"
    """
    phrases = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # First field is the phrase
            parts = line.split()
            if parts:
                phrases.append(parts[0])
    return phrases


def parse_data_txt(file_path: Path) -> List[str]:
    """Parse data.txt file and extract phrases.
    
    Format: phrase<TAB>score<TAB>... (tab-separated)
    Example: "_ctrl_punctuation_! ！ 0.0"
    """
    phrases = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # First field before whitespace is the phrase
            parts = line.split('\t')
            if parts:
                phrases.append(parts[0])
    return phrases


def parse_fixture_file(file_path: Path) -> Set[str]:
    """Parse fixture JSONL file and extract expected phrases.
    
    Format: JSON object with "expected" field
    Example: {"id": "tw-amb-001", "readings": [...], "expected": "再見", ...}
    """
    expected_phrases = set()
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                fixture = json.loads(line)
                if 'expected' in fixture:
                    expected_phrases.add(fixture['expected'])
            except json.JSONDecodeError:
                continue
    return expected_phrases


def extract_bigrams(phrase: str) -> List[Tuple[int, int]]:
    """Extract character bigrams from a phrase.
    
    Returns list of (codepoint_a, codepoint_b) tuples for adjacent characters.
    """
    bigrams = []
    phrase = phrase.strip()
    if len(phrase) < 2:
        return bigrams
    
    for i in range(len(phrase) - 1):
        cp_a = ord(phrase[i])
        cp_b = ord(phrase[i + 1])
        bigrams.append((cp_a, cp_b))
    
    return bigrams


def main():
    parser = argparse.ArgumentParser(description='Train bigram model from McBopomofo dictionary data')
    parser.add_argument('--input-dir', required=True, help='Path to Source/Data/ directory')
    parser.add_argument('--output', required=True, help='Path for .bin output file')
    parser.add_argument('--manifest', help='Path for manifest JSON output file')
    parser.add_argument('--exclude-fixtures', nargs='+', help='Path(s) to fixture JSONL files to exclude')
    parser.add_argument('--min-count', type=int, default=1, help='Minimum bigram count threshold')
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest) if args.manifest else None
    exclude_fixture_paths = [Path(p) for p in args.exclude_fixtures] if args.exclude_fixtures else []
    min_count = args.min_count
    
    # Collect all phrases from source files
    all_phrases = []
    
    # Read BPMFMappings.txt
    bpmf_mappings_path = input_dir / 'BPMFMappings.txt'
    if bpmf_mappings_path.exists():
        print(f"Reading {bpmf_mappings_path}...")
        bpmf_phrases = parse_bpmf_mappings(bpmf_mappings_path)
        all_phrases.extend(bpmf_phrases)
        print(f"  Extracted {len(bpmf_phrases)} phrases from BPMFMappings.txt")
    
    # Read data.txt
    data_txt_path = input_dir / 'data.txt'
    if data_txt_path.exists():
        print(f"Reading {data_txt_path}...")
        data_phrases = parse_data_txt(data_txt_path)
        all_phrases.extend(data_phrases)
        print(f"  Extracted {len(data_phrases)} phrases from data.txt")
    
    print(f"Total phrases before exclusion: {len(all_phrases)}")
    
    # Parse fixture files for exclusion
    excluded_fixture_ids = []
    excluded_fixture_phrases = set()
    
    for fixture_path in exclude_fixture_paths:
        if fixture_path.exists():
            print(f"Parsing fixture file: {fixture_path}")
            fixture_phrases = parse_fixture_file(fixture_path)
            excluded_fixture_ids.append(fixture_path.name)
            excluded_fixture_phrases.update(fixture_phrases)
            print(f"  Found {len(fixture_phrases)} expected phrases to exclude")
        else:
            print(f"Warning: Fixture file not found: {fixture_path}")
    
    # Filter out phrases that appear in fixtures
    filtered_phrases = []
    for phrase in all_phrases:
        if phrase not in excluded_fixture_phrases:
            filtered_phrases.append(phrase)
    
    print(f"Total phrases after exclusion: {len(filtered_phrases)}")
    print(f"Excluded {len(all_phrases) - len(filtered_phrases)} phrases from {len(excluded_fixture_ids)} fixture files")
    
    # Count unigrams and bigrams
    unigram_counts: Dict[int, int] = {}
    bigram_counts: Dict[Tuple[int, int], int] = {}
    
    for phrase in filtered_phrases:
        # Count unigrams
        for char in phrase:
            cp = ord(char)
            unigram_counts[cp] = unigram_counts.get(cp, 0) + 1
        
        # Count bigrams
        bigrams = extract_bigrams(phrase)
        for bigram in bigrams:
            bigram_counts[bigram] = bigram_counts.get(bigram, 0) + 1
    
    # Apply min-count threshold
    filtered_unigrams = {cp: count for cp, count in unigram_counts.items() if count >= min_count}
    filtered_bigrams = {bigram: count for bigram, count in bigram_counts.items() if count >= min_count}
    
    print(f"Unigrams after min-count filter: {len(filtered_unigrams)}")
    print(f"Bigrams after min-count filter: {len(filtered_bigrams)}")
    
    # Sort unigrams by codepoint
    sorted_unigrams = sorted(filtered_unigrams.items(), key=lambda x: x[0])
    
    # Sort bigrams by (cp_a, cp_b)
    sorted_bigrams = sorted(filtered_bigrams.items(), key=lambda x: (x[0][0], x[0][1]))
    
    # Create output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write BIGR binary file
    print(f"Writing BIGR model to {output_path}...")
    
    with open(output_path, 'wb') as f:
        # Write magic
        f.write(b'BIGR')
        
        # Write version
        f.write(struct.pack('<I', 1))
        
        # Write num_unigrams
        f.write(struct.pack('<I', len(sorted_unigrams)))
        
        # Write num_bigrams
        f.write(struct.pack('<I', len(sorted_bigrams)))
        
        # Write unigram entries
        for cp, count in sorted_unigrams:
            f.write(struct.pack('<I', cp))
            f.write(struct.pack('<I', count))
        
        # Write bigram entries
        for (cp_a, cp_b), count in sorted_bigrams:
            f.write(struct.pack('<I', cp_a))
            f.write(struct.pack('<I', cp_b))
            f.write(struct.pack('<I', count))
            # Compute log_prob = log(count_ab / count_a)
            log_prob = 0.0
            if cp_a in filtered_unigrams:
                count_a = filtered_unigrams[cp_a]
                if count_a > 0:
                    log_prob = __import__('math').log(count / count_a)
            f.write(struct.pack('<f', log_prob))
    
    # Compute model size and hash
    model_size = output_path.stat().st_size
    with open(output_path, 'rb') as f:
        model_hash = hashlib.sha256(f.read()).hexdigest()
    
    print(f"Model written: {model_size} bytes")
    print(f"Model SHA256: {model_hash}")
    
    # Write manifest JSON if requested
    if manifest_path:
        print(f"Writing manifest to {manifest_path}...")
        
        manifest = {
            "format_version": 1,
            "created_at": datetime.now().isoformat(),
            "source_files": ["BPMFMappings.txt", "data.txt"],
            "source_paths": [str(bpmf_mappings_path), str(data_txt_path)],
            "total_unigrams": len(sorted_unigrams),
            "total_bigrams": len(sorted_bigrams),
            "total_phrases_source": len(all_phrases),
            "total_phrases_after_exclusion": len(filtered_phrases),
            "excluded_fixture_ids": excluded_fixture_ids,
            "excluded_fixture_count": len(excluded_fixture_phrases),
            "model_path": str(output_path),
            "model_size_bytes": model_size,
            "model_sha256": model_hash,
            "min_count_threshold": min_count,
            "unique_characters": len(sorted_unigrams),
            "language": "Traditional Chinese",
            "taiwan_relevance": "high",
            "license": "MIT"
        }
        
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"Manifest written: {manifest_path}")
    
    print("Done!")


if __name__ == '__main__':
    main()
