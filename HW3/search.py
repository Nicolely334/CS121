def start(index):
    #just load 
    pass

def getPostings(term, lexicon, binFile):
    #get postings
    pass

def merge(listings):
    #merge posting lists
    pass

def rank(ids, lexicon, listings):
    #u want to score it and return a sorted list
    pass

def search(query, file, docMeta, lexicon):
    #just return top 5
    pass




def main():
    #1. ok starting point;
    #strategy: u want to call start() and loop thru user input
    #basically for this file u want to stem terms and for each term, look into index.bin
    #then score each return then return top 5
    pass

if __name__ == "__main__":
    main()