import re
from collections import Counter
from typing import List, Set

# Common physics stopwords to exclude from keyword extraction
STOPWORDS = {
    # General
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "this",
    "that", "these", "those", "it", "its", "we", "our", "they", "their",
    "which", "who", "whom", "what", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "same", "so", "than", "too",
    "very", "just", "also", "now", "here", "there", "then", "thus",
    "hence", "therefore", "however", "although", "though", "while",
    "since", "because", "if", "unless", "until", "after", "before",
    "between", "into", "through", "during", "above", "below", "up",
    "down", "out", "off", "over", "under", "again", "further", "once",

    # Physics common terms (too generic)
    "model", "models", "theory", "theories", "result", "results",
    "study", "studies", "analysis", "method", "methods", "approach",
    "data", "using", "show", "shows", "shown", "find", "found",
    "calculate", "calculated", "calculation", "calculations",
    "derive", "derived", "derivation", "obtain", "obtained",
    "consider", "considered", "investigate", "investigated",
    "discuss", "discussed", "present", "presented", "propose",
    "proposed", "introduce", "introduced", "describe", "described",
    "new", "recent", "first", "two", "three", "one", "case", "cases",
    "effect", "effects", "parameter", "parameters", "value", "values",
    "mass", "energy", "time", "space", "order", "leading", "next",
    "contribution", "contributions", "correction", "corrections",
    "term", "terms", "form", "level", "scale", "range", "limit",
    "coupling", "constant", "coefficient", "factor", "ratio",
}


def extract_keywords(title: str, abstract: str, max_keywords: int = 10) -> List[str]:
    """Extract significant keywords from title and abstract."""
    # Combine title (weighted more) and abstract
    text = f"{title} {title} {title} {abstract}"

    # Clean text
    text = text.lower()
    text = re.sub(r'[^\w\s-]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    # Tokenize
    words = text.split()

    # Filter stopwords and short words
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]

    # Count frequencies
    counter = Counter(words)

    # Get most common
    keywords = [word for word, _ in counter.most_common(max_keywords * 2)]

    # Also extract bigrams for physics terms
    bigrams = []
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i+1]}"
        if words[i] not in STOPWORDS and words[i+1] not in STOPWORDS:
            bigrams.append(bigram)

    bigram_counter = Counter(bigrams)
    top_bigrams = [bg for bg, count in bigram_counter.most_common(5) if count >= 2]

    # Combine, prioritizing bigrams
    result = top_bigrams + [w for w in keywords if w not in " ".join(top_bigrams)]

    return result[:max_keywords]


def normalize_author_name(name: str) -> str:
    """Normalize author name for comparison."""
    # Handle "Last, First" format
    if "," in name:
        parts = name.split(",")
        name = " ".join(reversed([p.strip() for p in parts]))

    # Lowercase and remove extra whitespace
    name = " ".join(name.lower().split())

    # Remove middle initials for comparison
    parts = name.split()
    if len(parts) > 2:
        # Keep first and last name
        name = f"{parts[0]} {parts[-1]}"

    return name


def names_match(name1: str, name2: str) -> bool:
    """Check if two author names likely refer to the same person."""
    n1 = normalize_author_name(name1)
    n2 = normalize_author_name(name2)

    if n1 == n2:
        return True

    # Check if one is substring of other (handles initials)
    parts1 = n1.split()
    parts2 = n2.split()

    # Same last name
    if parts1[-1] != parts2[-1]:
        return False

    # Check first name/initial match
    if parts1[0][0] == parts2[0][0]:
        return True

    return False


def calculate_relevance_score(
    candidate_papers: List,
    target_keywords: List[str],
    target_categories: List[str]
) -> float:
    """
    Calculate relevance score for a referee candidate.

    Factors:
    - Number of relevant papers
    - Keyword overlap
    - Category overlap
    """
    if not candidate_papers:
        return 0.0

    target_kw_set = set(kw.lower() for kw in target_keywords)
    target_cat_set = set(target_categories)

    scores = []
    for paper in candidate_papers:
        paper_text = f"{paper.title} {paper.abstract}".lower()
        paper_cats = set(paper.categories)

        # Keyword match score
        kw_matches = sum(1 for kw in target_kw_set if kw in paper_text)
        kw_score = kw_matches / max(len(target_kw_set), 1)

        # Category match score
        cat_overlap = len(paper_cats & target_cat_set)
        cat_score = cat_overlap / max(len(target_cat_set), 1)

        # Combined score for this paper
        paper_score = 0.7 * kw_score + 0.3 * cat_score
        scores.append(paper_score)

    # Overall score: average of top papers + bonus for multiple relevant papers
    if not scores:
        return 0.0

    top_scores = sorted(scores, reverse=True)[:3]
    avg_score = sum(top_scores) / len(top_scores)
    quantity_bonus = min(len(candidate_papers) * 0.05, 0.2)

    return min(avg_score + quantity_bonus, 1.0)
