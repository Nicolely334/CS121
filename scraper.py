import re
import json
import hashlib
from collections import Counter, defaultdict
from urllib.parse import urlparse, urldefrag, urljoin
from bs4 import BeautifulSoup

visited_urls = set()
word_counter = Counter()
subdomain_pages = defaultdict(set)

longest_page_url = ""
longest_page_word_count = 0
duplicate_hashes = set()
visited_patterns = defaultdict(int)

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off",
    "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "whom", "why", "with", "would", "you", "your", "yours", "yourself",
    "yourselves"
}
def scraper(url, resp):
    global longest_page_url, longest_page_word_count

    links = extract_next_links(url, resp)

    clean_url, _ = urldefrag(url)

    if resp.status == 200 and resp.raw_response and is_valid(clean_url):
        try:
            # Avoid counting/crawling duplicate pages with identical content
            content_hash = hashlib.md5(resp.raw_response.content).hexdigest()
            if content_hash in duplicate_hashes:
                return []
            duplicate_hashes.add(content_hash)

            if clean_url not in visited_urls:
                visited_urls.add(clean_url)

                parsed_url = urlparse(clean_url)
                hostname = parsed_url.hostname

                if hostname:
                    subdomain_pages[hostname].add(clean_url)

                soup = BeautifulSoup(resp.raw_response.content, "lxml")

                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()

                text = soup.get_text(separator=" ")
                words = re.findall(r"[a-zA-Z]+(?:'[a-zA-Z]+)?", text.lower())

                filtered_words = [
                    word for word in words
                    if word not in STOP_WORDS and len(word) > 1
                ]

                word_counter.update(filtered_words)

                word_count = len(words)

                if word_count > longest_page_word_count:
                    longest_page_word_count = word_count
                    longest_page_url = clean_url

                save_analytics()

        except Exception as e:
            print("Analytics error:", e)

    return [link for link in links if is_valid(link)]

def save_analytics():
    analytics = {
        "unique_pages": len(visited_urls),
        "longest_page": {
            "url": longest_page_url,
            "word_count": longest_page_word_count
        },
        "top_50_words": word_counter.most_common(50),
        "subdomains": {
            subdomain: len(urls)
            for subdomain, urls in sorted(subdomain_pages.items())
        }
    }

    with open("analytics.json", "w") as f:
        json.dump(analytics, f, indent=4)


def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
    output = []

    #ok code:
    #1. check if valid aka status 200
    if resp.status != 200 or not resp.raw_response:
        # return resp.error
        return []
    # also check if the files are very large
    if len(resp.raw_response.content) > 10000000:  # 10MB
        return []


    else:
        #now if valid:
        #2. parse html 
        parsed = BeautifulSoup(resp.raw_response.content, "lxml")
        for link in parsed.find_all("a"):
            find = link.get("href")
            
            if find:
                #first combine
                combined = urljoin(url, find)

                if '#' not in combined:
                    output.append(combined)

                else:
                    formatted, _ = urldefrag(combined)
                    output.append(formatted)

        return output #changed. put it outside of the for loop. 
            
    return [] #fallback!
def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    try:
        parsed = urlparse(url)

        if parsed.scheme not in set(["http", "https"]):
            return False
        
        #removed leading '.'
        allowedDomains = ["ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu"] 

        isValid = False
        curHost = parsed.hostname

        if not curHost:
            return False

        curHost = curHost.lower()
        path = parsed.path.lower()
        query = parsed.query.lower()

        #detect if there are any repeated URL path patterns -> crawler traps
        path_pattern = re.sub(r'\d+', 'N', path)
        visited_patterns[path_pattern] += 1

        if visited_patterns[path_pattern] > 50:
            return False

        #first check for valid domains
        for x in allowedDomains:
            if curHost == x or curHost.endswith("." + x): #changed
                isValid = True
                break
        
        #if not return False
        if not isValid:
            return False

        bad_hosts = {
            "gitlab.ics.uci.edu",
            "grape.ics.uci.edu",
        }

        if curHost in bad_hosts:
            return False

        if "doku.php" in path:
            return False

        if "/events/" in path or "/events/list" in path:
            return False

        if curHost == "fano.ics.uci.edu" and path.startswith("/ca/rules"):
            return False

        if curHost == "isg.ics.uci.edu" and path.startswith("/events"):
            return False

        if curHost == "www.ics.uci.edu" and path.startswith("/~eppstein/pix"):
            return False

        bad_path_terms = [
            "/calendar",
            "/login",
            "/task/todo",
            "/wp-json",
            "/feed",
            "/tag/",
            "/author/",
        ]

        if any(term in path for term in bad_path_terms):
            return False

        #no social media share links
        #no filters, calendar exports, tribe events, sorting, sessions
        bad_query_terms = [
            "share=",
            "entry_point=login",
            "filter",
            "tribe",
            "ical",
            "ecp_custom",
            "eventdisplay",
            "subpage",
            "replytocom",
            "sort",
            "orderby",
            "session",
            "login",
        ]

        if query and any(param in query for param in bad_query_terms):
            return False

        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|svg|webp|tiff?|mid|mp2|mp3|mp4|m4a"
            + r"|wav|avi|mov|mpeg|mpg|webm|flv|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|pps|ppsx|pot|potx"
            + r"|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|txt|xml|bib|java|py|apk|war|img"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", path)

    except (TypeError, ValueError):
        print("Invalid URL:", url)
        return False