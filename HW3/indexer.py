from __future__ import annotations

import argparse
import heapq
import html
import json
import math
import os
import re
import shutil
import struct
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Generator, Iterator, List, Optional, Tuple

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

IMPORTANT_WEIGHTS: Dict[str, int] = {
    "title":  5,
    "h1":     4,
    "h2":     3,
    "h3":     3,
    "b":      2,
    "strong": 2,
}

DEFAULT_FLUSH_THRESHOLD = 8_000


class PorterStemmer:
    _VOWELS = set("aeiou")

    def stem(self, word: str) -> str:
        word = word.lower()
        if len(word) <= 2:
            return word
        word = self._step1ab(word)
        word = self._step1c(word)
        word = self._step2(word)
        word = self._step3(word)
        word = self._step4(word)
        word = self._step5(word)
        return word

    def _is_consonant(self, word: str, i: int) -> bool:
        c = word[i]
        if c in self._VOWELS:
            return False
        if c == "y":
            return i == 0 or not self._is_consonant(word, i - 1)
        return True

    def _measure(self, word: str) -> int:
        """Count VC sequences (the 'm' value in Porter's paper)."""
        n, i, ln = 0, 0, len(word)

        while i < ln and self._is_consonant(word, i):
            i += 1
        while i < ln:
            while i < ln and not self._is_consonant(word, i):
                i += 1
            n += 1
            while i < ln and self._is_consonant(word, i):
                i += 1
        return n

    def _has_vowel(self, stem: str) -> bool:
        return any(not self._is_consonant(stem, i) for i in range(len(stem)))

    def _ends_double_consonant(self, word: str) -> bool:
        return (len(word) >= 2
                and word[-1] == word[-2]
                and self._is_consonant(word, len(word) - 1))

    def _ends_cvc(self, word: str) -> bool:
        """*o condition: ends with consonant-vowel-consonant where last c ≠ w,x,y."""
        if len(word) < 3:
            return False
        i = len(word) - 1
        return (self._is_consonant(word, i)
                and not self._is_consonant(word, i - 1)
                and self._is_consonant(word, i - 2)
                and word[i] not in "wxy")

    @staticmethod
    def _replace_suffix(word: str, suffix: str, replacement: str) -> Optional[str]:
        if word.endswith(suffix):
            return word[: len(word) - len(suffix)] + replacement
        return None

    def _step1ab(self, word: str) -> str:
        for suffix, replacement in [("sses", "ss"), ("ies", "i"),
                                     ("ss", "ss"), ("s", "")]:
            r = self._replace_suffix(word, suffix, replacement)
            if r is not None:
                word = r
                break

        changed = False
        if word.endswith("eed"):
            stem = word[:-3]
            if self._measure(stem) > 0:
                word = stem + "ee"
        elif word.endswith("ed"):
            stem = word[:-2]
            if self._has_vowel(stem):
                word, changed = stem, True
        elif word.endswith("ing"):
            stem = word[:-3]
            if self._has_vowel(stem):
                word, changed = stem, True

        if changed:
            for suffix, replacement in [("at", "ate"), ("bl", "ble"), ("iz", "ize")]:
                r = self._replace_suffix(word, suffix, replacement)
                if r is not None:
                    word = r
                    break
            else:
                if self._ends_double_consonant(word) and word[-1] not in "lsz":
                    word = word[:-1]
                elif self._measure(word) == 1 and self._ends_cvc(word):
                    word += "e"
        return word

    def _step1c(self, word: str) -> str:
        if word.endswith("y") and self._has_vowel(word[:-1]):
            word = word[:-1] + "i"
        return word

    def _step2(self, word: str) -> str:
        MAP = [
            ("ational", "ate"), ("tional", "tion"), ("enci", "ence"),
            ("anci", "ance"), ("izer", "ize"), ("abli", "able"),
            ("alli", "al"),   ("entli", "ent"), ("eli", "e"),
            ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
            ("ator", "ate"),  ("alism", "al"), ("iveness", "ive"),
            ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"),
            ("iviti", "ive"), ("biliti", "ble"),
        ]
        for suffix, replacement in MAP:
            r = self._replace_suffix(word, suffix, replacement)
            if r is not None and self._measure(r) > 0:
                return r
        return word

    def _step3(self, word: str) -> str:
        MAP = [
            ("icate", "ic"), ("ative", ""), ("alize", "al"),
            ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""),
        ]
        for suffix, replacement in MAP:
            r = self._replace_suffix(word, suffix, replacement)
            if r is not None and self._measure(r) > 0:
                return r
        return word

    def _step4(self, word: str) -> str:
        SUFFIXES = [
            "al", "ance", "ence", "er", "ic", "able", "ible", "ant",
            "ement", "ment", "ent", "ion", "ou", "ism", "ate", "iti",
            "ous", "ive", "ize",
        ]
        for suffix in SUFFIXES:
            r = self._replace_suffix(word, suffix, "")
            if r is not None:
                m = self._measure(r)
                if suffix == "ion":
                    if m > 1 and r and r[-1] in "st":
                        return r
                elif m > 1:
                    return r
        return word

    def _step5(self, word: str) -> str:
        if word.endswith("e"):
            stem = word[:-1]
            m = self._measure(stem)
            if m > 1 or (m == 1 and not self._ends_cvc(stem)):
                word = stem

        if (self._measure(word) > 1
                and self._ends_double_consonant(word)
                and word.endswith("l")):
            word = word[:-1]
        return word


def extract_text_weighted(html: str) -> Counter:
    stemmer = PorterStemmer()
    counts: Counter = Counter()

    class WeightedHTMLParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack: List[str] = []
            self.important_texts: List[Tuple[str, int]] = []
            self.body_text: List[str] = []
            self.current_text: List[str] = []
            self.current_weight = 1
            self.in_ignored = False

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
            if tag in {"script", "style"}:
                self.in_ignored = True
            self.stack.append(tag)
            self.current_weight = max(
                (IMPORTANT_WEIGHTS.get(t, 1) for t in self.stack), default=1
            )

        def handle_endtag(self, tag: str) -> None:
            if tag in {"script", "style"}:
                self.in_ignored = False
            if self.stack:
                self.stack.pop()
            self.current_weight = max(
                (IMPORTANT_WEIGHTS.get(t, 1) for t in self.stack), default=1
            )

        def handle_data(self, data: str) -> None:
            if self.in_ignored or not data.strip():
                return
            self.body_text.append(data)
            if any(tag in IMPORTANT_WEIGHTS for tag in self.stack):
                self.important_texts.append((data, self.current_weight))

        def get_texts(self) -> Tuple[List[str], List[Tuple[str, int]]]:
            return self.body_text, self.important_texts

    parser = WeightedHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        for tok in TOKEN_RE.findall(html):
            counts[stemmer.stem(tok)] += 1
        return counts

    body_text, important_texts = parser.get_texts()

    for tok in TOKEN_RE.findall(" ".join(body_text)):
        counts[stemmer.stem(tok)] += 1
    for text, weight in important_texts:
        for tok in TOKEN_RE.findall(text):
            counts[stemmer.stem(tok)] += weight
    return counts


class PartialIndex:
    """
    Postings structure (in memory):
        { term: { doc_id: weighted_tf } }
    """

    def __init__(self) -> None:
        self._data: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._token_count = 0

    def add(self, doc_id: int, term_counts: Counter) -> None:
        for term, count in term_counts.items():
            self._data[term][doc_id] = count
        self._token_count += sum(term_counts.values())

    def flush(self, path: Path) -> None:
        """Write sorted postings to a JSON file and clear memory."""
        serialisable = {
            term: sorted(postings.items())
            for term, postings in sorted(self._data.items())
        }
        path.write_text(json.dumps(serialisable, separators=(',', ':')), encoding="utf-8")
        self._data.clear()
        self._token_count = 0

    @property
    def token_count(self) -> int:
        return self._token_count

    def __len__(self) -> int:
        return len(self._data)


def iter_partial(path: Path) -> Iterator[Tuple[str, List[Tuple[int, int]]]]:
    """Yield (term, postings_list) from a partial index file, in sorted order."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for term in sorted(data.keys()):
        yield term, data[term]


POSTING_STRUCT = struct.Struct("<II")
POSTING_SIZE   = POSTING_STRUCT.size


def encode_postings(postings: List[Tuple[int, int]]) -> bytes:
    return b"".join(POSTING_STRUCT.pack(doc_id, tf) for doc_id, tf in postings)


def decode_postings(raw: bytes) -> List[Tuple[int, int]]:
    n = len(raw) // POSTING_SIZE
    return [POSTING_STRUCT.unpack_from(raw, i * POSTING_SIZE) for i in range(n)]


def merge_partials(
    partial_paths: List[Path],
    output_bin: Path,
    output_lexicon: Path,
    num_docs: int,
) -> Dict[str, Tuple[int, int, int]]:
    """
    Merge all partial index files into one sorted binary postings file.

    Returns the lexicon as {term: (byte_offset, byte_length, df)}.
    """

    iterators = [iter_partial(p) for p in partial_paths]

    heap: List[Tuple[str, List[Tuple[int, int]], int]] = []
    for idx, it in enumerate(iterators):
        try:
            term, postings = next(it)
            heapq.heappush(heap, (term, postings, idx))
        except StopIteration:
            pass

    lexicon: Dict[str, Tuple[int, int, int]] = {}
    offset = 0

    with open(output_bin, "wb") as fout:
        while heap:
            current_term, current_postings, idx = heapq.heappop(heap)
            try:
                next_term, next_postings = next(iterators[idx])
                heapq.heappush(heap, (next_term, next_postings, idx))
            except StopIteration:
                pass

            merged: Dict[int, int] = dict(current_postings)
            while heap and heap[0][0] == current_term:
                _, more_postings, idx2 = heapq.heappop(heap)
                for doc_id, tf in more_postings:
                    merged[doc_id] = merged.get(doc_id, 0) + tf
                try:
                    next_term2, next_postings2 = next(iterators[idx2])
                    heapq.heappush(heap, (next_term2, next_postings2, idx2))
                except StopIteration:
                    pass

            sorted_postings = sorted(merged.items())
            raw = encode_postings(sorted_postings)
            fout.write(raw)
            df = len(sorted_postings)
            lexicon[current_term] = (offset, len(raw), df)
            offset += len(raw)

    return lexicon


def iter_corpus(corpus_root: Path) -> Generator[Tuple[str, str], None, None]:
    """
    Yield (url, html_content) for every JSON file found under corpus_root.

    The DEV folder structure is: corpus_root/<domain>/<file>.json
    """
    for domain_dir in sorted(corpus_root.iterdir()):
        if not domain_dir.is_dir():
            continue
        for json_file in sorted(domain_dir.iterdir()):
            if json_file.suffix != ".json":
                continue
            try:
                data = json.loads(json_file.read_bytes())
            except Exception:
                continue
            url: str = data.get("url", "")
            content: str = data.get("content", "")

            if "#" in url:
                url = url[: url.index("#")]
            if url and content:
                yield url, content


def build_index(
    corpus_root: Path,
    index_dir: Path,
    flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    partials_dir = index_dir / "partials"
    partials_dir.mkdir(exist_ok=True)

    partial = PartialIndex()
    partial_paths: List[Path] = []
    partial_count = 0

    doc_meta: Dict[int, Dict] = {}
    seen_urls: set = set()
    doc_id = 0
    total_tokens = 0

    print("Phase 1: Tokenising and building partial indexes…")

    for url, html in iter_corpus(corpus_root):
        if url in seen_urls:
            continue
        seen_urls.add(url)

        term_counts = extract_text_weighted(html)
        if not term_counts:
            continue

        doc_length = sum(term_counts.values())
        doc_meta[doc_id] = {"url": url, "length": doc_length}
        total_tokens += doc_length

        partial.add(doc_id, term_counts)
        doc_id += 1

        if doc_id % 1_000 == 0:
            print(f"  Processed {doc_id:,} documents…", end="\r", flush=True)

        if doc_id % flush_threshold == 0:
            partial_count += 1
            ppath = partials_dir / f"partial_{partial_count:04d}.json"
            print(f"\n  → Flushing partial index #{partial_count} "
                  f"({len(partial):,} terms) to {ppath.name}")
            partial.flush(ppath)
            partial_paths.append(ppath)

    if partial._data:
        partial_count += 1
        ppath = partials_dir / f"partial_{partial_count:04d}.json"
        print(f"\n  → Flushing final partial index #{partial_count} "
              f"({len(partial):,} terms) to {ppath.name}")
        partial.flush(ppath)
        partial_paths.append(ppath)

    num_docs = doc_id
    print(f"\nPhase 1 complete: {num_docs:,} documents, "
          f"{partial_count} partial index files.")

    print("\nPhase 2: Merging partial indexes…")
    bin_path     = index_dir / "index.bin"
    lexicon_path = index_dir / "lexicon.json"

    lexicon = merge_partials(partial_paths, bin_path, lexicon_path, num_docs)
    print(f"  Merge complete: {len(lexicon):,} unique terms.")

    print("\nPhase 3: Computing IDF and writing lexicon…")

    final_lexicon: Dict[str, List] = {}
    for term, (offset, length, df) in lexicon.items():
        idf = math.log((num_docs + 1) / (df + 1)) + 1.0
        final_lexicon[term] = [offset, length, df, round(idf, 6)]

    lexicon_path.write_text(
        json.dumps(final_lexicon, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"  Lexicon written to {lexicon_path}")

    (index_dir / "doc_meta.json").write_text(
        json.dumps(doc_meta, separators=(",", ":")),
        encoding="utf-8",
    )
    (index_dir / "stats.json").write_text(
        json.dumps({
            "num_docs":   num_docs,
            "num_terms":  len(final_lexicon),
            "num_tokens": total_tokens,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"  Metadata written to {index_dir / 'doc_meta.json'}")
    print(f"  Stats written to {index_dir / 'stats.json'}")

    shutil.rmtree(partials_dir)
    print(f"\n  Temporary partial files removed.")

    bin_size_mb = bin_path.stat().st_size / 1_048_576
    print(
        f"\n{'='*55}\n"
        f"  Indexing complete!\n"
        f"  Documents indexed : {num_docs:,}\n"
        f"  Unique terms      : {len(final_lexicon):,}\n"
        f"  Total tokens      : {total_tokens:,}\n"
        f"  Postings file     : {bin_path} ({bin_size_mb:.1f} MB)\n"
        f"{'='*55}"
    )


def load_lexicon(index_dir: Path) -> Dict[str, Tuple[int, int, int, float]]:
    lexicon_path = index_dir / "lexicon.json"
    if not lexicon_path.exists():
        raise FileNotFoundError(f"Missing lexicon file: {lexicon_path}")
    raw = json.loads(lexicon_path.read_text(encoding="utf-8"))
    return {
        term: (offset, length, df, float(idf))
        for term, (offset, length, df, idf) in raw.items()
    }


def load_doc_meta(index_dir: Path) -> Dict[int, Dict[str, int]]:
    doc_meta_path = index_dir / "doc_meta.json"
    if not doc_meta_path.exists():
        raise FileNotFoundError(f"Missing document metadata file: {doc_meta_path}")
    raw = json.loads(doc_meta_path.read_text(encoding="utf-8"))
    return {int(doc_id): meta for doc_id, meta in raw.items()}


def read_postings(index_bin_path: Path, offset: int, length: int) -> List[Tuple[int, int]]:
    with open(index_bin_path, "rb") as fin:
        fin.seek(offset)
        raw = fin.read(length)
    return decode_postings(raw)


def normalize_query(query: str) -> List[str]:
    stemmer = PorterStemmer()
    return [stemmer.stem(tok) for tok in TOKEN_RE.findall(query) if tok]


def search_index(index_dir: Path, query: str, top_k: int = 20) -> List[Tuple[float, int, str]]:
    lexicon = load_lexicon(index_dir)
    doc_meta = load_doc_meta(index_dir)
    query_terms = normalize_query(query)

    if not query_terms:
        return []

    index_bin_path = index_dir / "index.bin"
    term_postings: List[Tuple[str, float, Dict[int, int]]] = []

    for term in query_terms:
        if term not in lexicon:
            return []
        offset, length, _, idf = lexicon[term]
        postings = dict(read_postings(index_bin_path, offset, length))
        term_postings.append((term, idf, postings))

    common_doc_ids = set(term_postings[0][2].keys())
    for _, _, postings in term_postings[1:]:
        common_doc_ids &= postings.keys()
        if not common_doc_ids:
            return []

    results: List[Tuple[float, int, str]] = []
    for doc_id in sorted(common_doc_ids):
        score = sum(postings[doc_id] * idf for _, idf, postings in term_postings)
        url = doc_meta.get(doc_id, {}).get("url", "")
        results.append((score, doc_id, url))

    results.sort(key=lambda item: (-item[0], item[1]))
    return results[:top_k]


def print_search_results(index_dir: Path, query: str, top_k: int = 20) -> None:
    results = search_index(index_dir, query, top_k)
    print(f"Query: {query}")
    if not results:
        print("No matching documents found.")
        return

    print(f"Top {len(results)} results:")
    for rank, (score, doc_id, url) in enumerate(results, start=1):
        print(f"{rank}. {url} (doc_id={doc_id}, score={score:.4f})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ICS Search Engine Indexer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "corpus_root",
        type=Path,
        nargs="?",
        help="Path to the extracted DEV folder (contains one sub-folder per domain).",
    )
    parser.add_argument(
        "index_dir",
        type=Path,
        help="Directory where index files will be written or read from.",
    )
    parser.add_argument(
        "--flush-threshold",
        type=int,
        default=DEFAULT_FLUSH_THRESHOLD,
        metavar="N",
        help=f"Flush a partial index after every N documents (default: {DEFAULT_FLUSH_THRESHOLD}).",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Run a boolean AND search query against an existing index.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Maximum number of search results to display.",
    )
    args = parser.parse_args()

    if args.query:
        if not args.index_dir.is_dir():
            sys.exit(f"Error: index directory '{args.index_dir}' is not a directory.")
        print_search_results(args.index_dir, args.query, args.top_k)
        return

    if not args.corpus_root or not args.corpus_root.is_dir():
        sys.exit(f"Error: corpus root '{args.corpus_root}' is not a directory.")

    build_index(
        corpus_root=args.corpus_root,
        index_dir=args.index_dir,
        flush_threshold=args.flush_threshold,
    )


if __name__ == "__main__":
    main()