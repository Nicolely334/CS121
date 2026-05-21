from indexer import PorterStemmer, POSTING_SIZE

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

def merge(listings):
    #merge posting lists
    pass

def score(lexicon, remaining, stems, docMeta):
    #u want to score each doc (normalised) and return a sorted list
    output = []

    for docID, freq in remaining:
        if "length" in docMeta[docID]:
            docLen = docMeta[docID]["length"]

            if docLen == 0:
                docLen = 1

        else:
            docLen = 1


        score = 0

        for i in range(len(stems)):
            term = stems[i]

            tf = freq[i]
            idf = lexicon[term][3] #bc at index 3 in lexicon entry

            score += (tf * idf)

            #normalize:
            score = score/math.sqrt(docLen)

            #tehn append:
            output.append((score, docID))

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
    ranked = score(remaining, finalStem, lexicon, docMeta)

    #6. print! yay
    topRes = min(5, len(ranked))

    for i in range(topRes):
        scoreValue = ranked[i][0]
        docID = ranked[i][1]
        url = docMeta[docID]["url"]

        print(str(i + 1) + ". " + url)
        print("score:", round(scoreValue, 4))


def main():
    #1. ok starting point;
    #strategy: u want to call start() and loop thru user input
    #basically for this file u want to stem terms and for each term, look into index.bin
    #then score each return then return top 5
    pass

if __name__ == "__main__":
    main()