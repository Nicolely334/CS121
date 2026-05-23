import json
import math
import re
import argparse
import struct
from pathlib import Path
from indexer import PorterStemmer, POSTING_SIZE

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
POSTING_STRUCT = struct.Struct("!If")

def start(index):
    #just load lexicon and doc meta into mem
    
    lexicon = index / "lexicon.json"
    docMeta = index / "doc_meta.json"
    path = index / "index.bin"

    #first check if files exist:
    files = [lexicon, docMeta, path]

    for file in files: 
        if not file.exists():
            return "error dne"
        
    #load lexicon
    with open(lexicon, "r", encoding="utf-8") as f:
        lexi = json.load(f)

    #load metadata
    with open(docMeta, "r", encoding="utf-8") as f:
        meta = json.load(f)

    #now load doc id (change from str to ints)!
    data = {}
    for id,info in meta.items():
        data[int(id)] = info


    #load binary
    index_binary = open(path, "rb")

    return lexi, data, index_binary

def getPostings(term, lexicon, binFile):
    #get postings for 1 term;; want to return a list of doc id, tf
    
    if term not in lexicon:
        return []
    
    start = lexicon[term]
    offset = start[0]
    size = start[1]

    #get to right pos in binary file
    binFile.seek(offset)
    rawData = binFile.read(size)
    postingSize = len(rawData) // POSTING_SIZE

    output = []
    for i in range(postingSize):
        startPos = POSTING_SIZE * i
        x = POSTING_STRUCT.unpack_from(rawData, startPos)
        output.append(x)

    return output

def merge(posting_lists):
    #merge posting lists

    # nothing to merge
    if not posting_lists:
        return {}

    # sort lists by length so we start with the rarest (shortest) term.
    order = sorted(range(len(posting_lists)), key=lambda i: len(posting_lists[i]))
    sorted_lists = [posting_lists[i] for i in order]

    # seed the result from the shortest list.
    result = {doc_id: [0] * len(posting_lists) for doc_id, _ in sorted_lists[0]}

    # fill in the TFs for the first (shortest) list.
    for doc_id, tf in sorted_lists[0]:
        result[doc_id][order[0]] = tf

    # intersect with each remaining list one by one
    for rank, postings in enumerate(sorted_lists[1:], start=1):

        # build a lookup dict for fast membership checks
        posting_map = {doc_id: tf for doc_id, tf in postings}

        # keep only docs that also appear in this list
        result = {
            doc_id: tfs
            for doc_id, tfs in result.items()
            if doc_id in posting_map
        }

        # for surviving docs, fill in the TF at the correct position.
        orig_idx = order[rank]
        for doc_id in result:
            result[doc_id][orig_idx] = posting_map[doc_id]

    return result

def score(lexicon, remaining, stems, docMeta):
    #u want to score each doc (normalised) and return a sorted list
    output = []

    for docID, freq in remaining.items():
        if docID not in docMeta:
            continue
        if "length" in docMeta[docID]:
            docLen = docMeta[docID]["length"]

            if docLen == 0:
                docLen = 1

        else:
            docLen = 1


        doc_score = 0

        for i in range(len(stems)):
            term = stems[i]

            tf = freq[i]
            idf = lexicon[term][3] #bc at index 3 in lexicon entry

            doc_score += (tf * idf)

            #normalize:
        doc_score = doc_score/math.sqrt(docLen)

            #tehn append:
        output.append((doc_score, docID))

    output.sort(reverse=True)
    return output

def search(query, docMeta, lexicon, binFile, stemmer):
    #calls all helper funcs and returns top 5

    #1. tokenize
    tokens = TOKEN_RE.findall(query)
    
    #check if == 0
    if len(tokens) == 0:
        return #empty!
    
    #2. stem
    stemm = []
    for x in tokens:
        stem = stemmer.stem(x)
        stemm.append(stem)

    #2.5 filter out -- only want ones start in range
    finalStem = []
    for x in stemm:
        if x in lexicon:
            finalStem.append(x)

    #check if final is empty
    if len(finalStem) == 0:
        return

    #3. get postings
    postings = []
    for x in finalStem:
        post = getPostings(x, lexicon, binFile)
        postings.append(post)

    #4. find docs
    remaining = merge(postings)
    if len(remaining) == 0:
        return

    #5. score
    ranked = score(lexicon, remaining, finalStem, docMeta)

    #6. print! yay
    topRes = min(5, len(ranked))

    for i in range(topRes):
        scoreValue = ranked[i][0]
        docID = ranked[i][1]
        url = docMeta[docID]["url"]

        print(str(i + 1) + ". " + url)
        print("score:", round(scoreValue, 4))


def main() -> None:
    # set up command line argument parsing
    parser = argparse.ArgumentParser(
        description="ICS Search Engine — query interface",
    )
    # index_dir is the folder containing lexicon.json, index.bin, doc_meta.json
    parser.add_argument(
        "index_dir",
        type=Path,
        help="Directory produced by indexer.py (contains lexicon.json, index.bin, doc_meta.json).",
    )
    args = parser.parse_args()

    # load lexicon, doc metadata, and binary index file into memory
    lexicon, doc_meta, bin_file = start(args.index_dir)

    # create stemmer instance
    stemmer = PorterStemmer()

    print("\nSearch ready. Type a query and press Enter. Empty input to quit.\n")

    try:
        # keep looping until user enters empty input or EOF
        while True:
            try:
                query = input("Query> ").strip()
            except EOFError:
                # handles piped input ending
                break
            if not query:
                # empty input means quit
                break
            # run the search and print top 5 results
            search(query, doc_meta, lexicon, bin_file, stemmer)
    finally:
        # always close the binary file even if something crashes
        bin_file.close()


if __name__ == "__main__":
    main()