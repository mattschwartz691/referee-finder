import requests
import time
from collections import defaultdict
from datetime import datetime
from typing import List, Optional, Set, Dict
from .models import Author, Paper


class InspireClient:
    """Client for interacting with INSPIRE-HEP API."""

    BASE_URL = "https://inspirehep.net/api"

    RANK_MAP = {
        "UNDERGRADUATE": "Graduate Student",
        "MASTER": "Graduate Student",
        "PHD": "Graduate Student",
        "POSTDOC": "Postdoc",
        "JUNIOR": "Junior Faculty",
        "SENIOR": "Senior",
        "STAFF": "Mid-Career",
        "VISITOR": None,
    }

    def __init__(self, delay: float = 0.3):
        self.session = requests.Session()
        self.delay = delay
        self._last_request = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        self._rate_limit()
        url = f"{self.BASE_URL}/{endpoint}"
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2)  # Longer wait
                    continue
        if last_error:
            print(f"INSPIRE API error after {max_retries} retries: {last_error}")
        return None

    def search_author(self, name: str) -> Optional[dict]:
        name_parts = name.split()
        if len(name_parts) >= 2:
            search_name = f"{name_parts[-1]}, {name_parts[0]}"
        else:
            search_name = name

        params = {
            "q": f"a {search_name}",
            "size": 5,
        }
        data = self._get("authors", params)

        if not data or "hits" not in data:
            return None

        hits = data["hits"].get("hits", [])
        return hits[0] if hits else None

    def get_author_info(self, name: str) -> Optional[Author]:
        """Get full author information including career data."""
        author_data = self.search_author(name)
        if not author_data:
            return None

        metadata = author_data.get("metadata", {})
        inspire_id = author_data.get("id")

        # Extract ORCID
        orcid = None
        for id_info in metadata.get("ids", []):
            if id_info.get("schema") == "ORCID":
                orcid = id_info.get("value")
                break

        # Extract institution and rank from positions
        institution = None
        current_rank = None
        phd_year = None
        phd_institution = None
        first_paper_year = None
        positions = metadata.get("positions", [])

        for pos in positions:
            if pos.get("current"):
                institution = pos.get("institution")
                current_rank = pos.get("rank")
                break

        if not institution and positions:
            institution = positions[0].get("institution")
            if not current_rank:
                current_rank = positions[0].get("rank")

        # Find PhD position and earliest position
        for pos in positions:
            rank = pos.get("rank")
            start = pos.get("start_date")
            end = pos.get("end_date")

            # Extract PhD info
            if rank == "PHD":
                if end:
                    try:
                        phd_year = int(end.split("-")[0])
                    except (ValueError, IndexError):
                        pass
                phd_institution = pos.get("institution")

        # Get first paper year from earliest position
        for pos in reversed(positions):
            start = pos.get("start_date")
            if start:
                try:
                    first_paper_year = int(start.split("-")[0])
                    break
                except (ValueError, IndexError):
                    pass

        author_name = metadata.get("name", {}).get("value", name)
        if not author_name:
            author_name = metadata.get("name", {}).get("preferred_name", name)

        author = Author(
            name=author_name,
            inspire_id=inspire_id,
            orcid=orcid,
            institution=institution,
            first_paper_year=first_paper_year,
            phd_year=phd_year,
            phd_institution=phd_institution
        )

        if current_rank and current_rank in self.RANK_MAP:
            mapped_stage = self.RANK_MAP[current_rank]
            if mapped_stage:
                author._rank_stage = mapped_stage

        return author

    def get_author_papers_with_counts(
        self, author_name: str, years: int = 3, max_results: int = 100
    ) -> tuple[List[Paper], Dict[int, int]]:
        """
        Get recent papers by an author and count small-collaboration papers by year.

        Returns:
            Tuple of (list of papers, dict mapping year -> count of papers with <10 authors)
        """
        current_year = datetime.now().year
        start_year = current_year - years

        name_parts = author_name.split()
        if len(name_parts) >= 2:
            search_name = f"{name_parts[-1]}, {name_parts[0]}"
        else:
            search_name = author_name

        params = {
            "q": f'a "{search_name}" and date>{start_year}',
            "size": max_results,
            "sort": "mostrecent",
        }
        data = self._get("literature", params)

        if not data or "hits" not in data:
            return [], {}

        papers = []
        small_collab_by_year: Dict[int, int] = defaultdict(int)

        for hit in data["hits"].get("hits", []):
            metadata = hit.get("metadata", {})

            arxiv_eprints = metadata.get("arxiv_eprints", [])
            arxiv_id = arxiv_eprints[0].get("value") if arxiv_eprints else None
            if not arxiv_id:
                continue

            titles = metadata.get("titles", [])
            title = titles[0].get("title") if titles else "Unknown"

            abstracts = metadata.get("abstracts", [])
            abstract = abstracts[0].get("value") if abstracts else ""

            authors_data = metadata.get("authors", [])
            num_authors = len(authors_data)
            authors = [a.get("full_name", "") for a in authors_data[:10]]

            categories = metadata.get("arxiv_categories", [])

            earliest = metadata.get("earliest_date", "")
            try:
                pub_date = datetime.strptime(earliest, "%Y-%m-%d")
            except ValueError:
                try:
                    pub_date = datetime.strptime(earliest, "%Y-%m")
                except ValueError:
                    pub_date = datetime.now()

            paper = Paper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                authors=authors,
                categories=categories,
                published=pub_date,
                inspire_id=hit.get("id"),
                num_authors=num_authors
            )
            papers.append(paper)

            # Count small-collaboration papers (<10 authors)
            if num_authors < 10:
                small_collab_by_year[pub_date.year] += 1

        return papers, dict(small_collab_by_year)

    def get_author_papers(
        self, author_name: str, years: int = 3, max_results: int = 50
    ) -> List[Paper]:
        """Get recent papers by an author."""
        papers, _ = self.get_author_papers_with_counts(author_name, years, max_results)
        return papers

    def get_collaborators(self, author_name: str, years: int = 3) -> Set[str]:
        papers = self.get_author_papers(author_name, years=years, max_results=100)

        collaborators = set()
        for paper in papers:
            for coauthor in paper.authors:
                coauthor_normalized = self._normalize_name(coauthor)
                author_normalized = self._normalize_name(author_name)
                if coauthor_normalized != author_normalized:
                    collaborators.add(coauthor)

        return collaborators

    def is_active(self, author_name: str, months: int = 12) -> bool:
        papers = self.get_author_papers(author_name, years=2, max_results=10)
        if not papers:
            return False

        cutoff = datetime(datetime.now().year - 1, datetime.now().month, 1)
        return any(p.published >= cutoff for p in papers)

    def _normalize_name(self, name: str) -> str:
        if "," in name:
            parts = name.split(",")
            name = " ".join(reversed([p.strip() for p in parts]))
        return " ".join(name.lower().split())

    def check_collaboration(
        self, author_name: str, paper_authors: List[str], years: int = 3
    ) -> bool:
        collaborators = self.get_collaborators(author_name, years=years)

        collab_normalized = {self._normalize_name(c) for c in collaborators}
        paper_normalized = {self._normalize_name(a) for a in paper_authors}

        return bool(collab_normalized & paper_normalized)

    def get_paper_references(self, arxiv_id: str) -> List[str]:
        """Get INSPIRE record IDs of papers referenced by this paper."""
        params = {
            "q": f"arxiv:{arxiv_id}",
            "size": 1,
        }
        data = self._get("literature", params)

        if not data or not data.get("hits", {}).get("hits"):
            return []

        metadata = data["hits"]["hits"][0].get("metadata", {})
        references = metadata.get("references", [])

        ref_ids = []
        for ref in references:
            record = ref.get("record", {})
            ref_url = record.get("$ref", "")
            if "/literature/" in ref_url:
                ref_id = ref_url.split("/literature/")[-1]
                ref_ids.append(ref_id)

        return ref_ids

    def get_paper_references_by_topic(self, arxiv_id: str, topic_keywords: List[str]) -> tuple[List[str], List[str]]:
        """
        Get references from a paper, separated by whether they match the topic keywords.
        This helps find papers citing the topic-specific references rather than method references.

        Returns: (topic_refs, method_refs)
        """
        params = {
            "q": f"arxiv:{arxiv_id}",
            "size": 1,
        }
        data = self._get("literature", params)

        if not data or not data.get("hits", {}).get("hits"):
            return [], []

        metadata = data["hits"]["hits"][0].get("metadata", {})
        references = metadata.get("references", [])

        topic_refs = []
        method_refs = []

        # Expand keywords to match more variations
        topic_kw_lower = []
        for kw in topic_keywords:
            kw_lower = kw.lower()
            topic_kw_lower.append(kw_lower)
            # Also add individual significant words from multi-word phrases
            words = kw_lower.split()
            for word in words:
                if word not in ['the', 'of', 'in', 'and', 'or', 'a', 'an', 'for'] and len(word) > 4:
                    topic_kw_lower.append(word)
            # Add variations
            if "super-renormalizable" in kw_lower:
                topic_kw_lower.extend(["superrenormalizable", "super-renormaliz", "super renormalizable"])
            if "gravity" in kw_lower:
                topic_kw_lower.extend(["gravitational", "gravit"])
            if "higher derivative" in kw_lower:
                topic_kw_lower.extend(["higher-derivative", "quadratic"])
            if "nonlocal" in kw_lower or "non-local" in kw_lower:
                topic_kw_lower.extend(["nonlocal", "non-local", "infinite derivative"])

        # Remove duplicates
        topic_kw_lower = list(set(topic_kw_lower))

        for ref in references:
            record = ref.get("record", {})
            ref_url = record.get("$ref", "")
            if "/literature/" not in ref_url:
                continue

            ref_id = ref_url.split("/literature/")[-1]

            # Get the reference's title to classify it
            ref_data = self._get(f"literature/{ref_id}")
            if not ref_data or "metadata" not in ref_data:
                method_refs.append(ref_id)  # Default to method if can't fetch
                continue

            ref_title = ref_data["metadata"].get("titles", [{}])[0].get("title", "").lower()

            # Check if title matches any topic keywords (flexible matching)
            is_topic_ref = any(kw in ref_title for kw in topic_kw_lower if len(kw) > 3)

            # Also check for specific gravity-related terms that indicate topic relevance
            gravity_topic_terms = ["ghost free", "ghost-free", "singularity free", "singularity-free",
                                   "f(r) gravity", "higher order gravity", "quadratic gravity",
                                   "nonlocal gravity", "infinite derivative", "quantum gravity"]
            if any(term in ref_title for term in gravity_topic_terms):
                is_topic_ref = True

            if is_topic_ref:
                topic_refs.append(ref_id)
            else:
                method_refs.append(ref_id)

        return topic_refs, method_refs

    def calculate_mainstream_index(self, arxiv_id: str) -> tuple[float, dict]:
        """
        Calculate how mainstream a paper is based on:
        1. Citation counts of its references (mainstream papers cite well-known works)
        2. Total number of references (mainstream papers have more standard refs)
        3. How recent the references are (niche work often cites older foundational papers)

        Returns: (mainstream_index 0-1, details dict)
        """
        params = {
            "q": f"arxiv:{arxiv_id}",
            "size": 1,
        }
        data = self._get("literature", params)

        if not data or not data.get("hits", {}).get("hits"):
            return 0.5, {"error": "Paper not found"}

        metadata = data["hits"]["hits"][0].get("metadata", {})
        references = metadata.get("references", [])

        if not references:
            return 0.5, {"error": "No references found"}

        # Sample some references to check their citation counts
        ref_ids = []
        for ref in references:
            record = ref.get("record", {})
            ref_url = record.get("$ref", "")
            if "/literature/" in ref_url:
                ref_id = ref_url.split("/literature/")[-1]
                ref_ids.append(ref_id)

        if not ref_ids:
            return 0.5, {"error": "No linked references"}

        # Check citation counts for a sample of references
        import random
        sample_size = min(10, len(ref_ids))
        sample_refs = random.sample(ref_ids, sample_size)

        citation_counts = []
        for ref_id in sample_refs:
            ref_data = self._get(f"literature/{ref_id}")
            if ref_data and "metadata" in ref_data:
                citations = ref_data["metadata"].get("citation_count", 0)
                citation_counts.append(citations)

        if not citation_counts:
            return 0.5, {"error": "Could not fetch reference data"}

        # Calculate metrics
        avg_citations = sum(citation_counts) / len(citation_counts)
        max_citations = max(citation_counts)

        # Mainstream papers typically cite papers with ~100+ citations on average
        # Niche papers cite more specialized work with fewer citations
        # Using log scale: 10 citations = 0.3, 100 citations = 0.6, 1000 = 0.9
        import math
        citation_score = min(math.log10(avg_citations + 1) / 3, 1.0) if avg_citations > 0 else 0.1

        # Number of references: more refs = more mainstream (typically)
        # 20 refs = 0.3, 50 refs = 0.6, 100+ refs = 0.9
        ref_count_score = min(len(references) / 100, 0.9)

        # Combined score
        mainstream_index = 0.7 * citation_score + 0.3 * ref_count_score

        details = {
            "avg_ref_citations": round(avg_citations, 1),
            "max_ref_citations": max_citations,
            "num_references": len(references),
            "citation_score": round(citation_score, 2),
            "ref_count_score": round(ref_count_score, 2),
        }

        return round(mainstream_index, 2), details

    def get_papers_citing_refs(
        self, ref_ids: List[str], months_start: int = 2, months_end: int = 12, max_results: int = 200
    ) -> List[dict]:
        """
        Find papers that cite any of the given reference IDs.
        Returns papers published in the date range that share references.
        """
        if not ref_ids:
            return []

        from datetime import datetime, timedelta

        # Calculate date range
        now = datetime.now()
        date_start = now - timedelta(days=months_end * 30)
        date_end = now - timedelta(days=months_start * 30)

        # Search for papers citing these references
        # Sample refs from throughout the list, not just the first few
        # This helps when papers bridge multiple fields
        import random
        if len(ref_ids) <= 5:
            sample_refs = ref_ids
        else:
            # Take refs from beginning, middle, and end of reference list
            n = len(ref_ids)
            indices = [0, 1, n//3, 2*n//3, n-2, n-1]
            # Add some random ones
            indices.extend(random.sample(range(n), min(4, n)))
            indices = list(set(i for i in indices if 0 <= i < n))[:8]
            sample_refs = [ref_ids[i] for i in sorted(indices)]

        ref_query = " or ".join([f"refersto:recid:{rid}" for rid in sample_refs])

        params = {
            "q": f"({ref_query})",
            "size": max_results,
            "sort": "mostrecent",
        }
        data = self._get("literature", params)

        if not data or "hits" not in data:
            return []

        # Filter by date in Python (to avoid complex INSPIRE query)
        hits_list = []
        for hit in data["hits"].get("hits", []):
            metadata = hit.get("metadata", {})
            earliest = metadata.get("earliest_date", "")
            try:
                pub_date = datetime.strptime(earliest, "%Y-%m-%d")
            except ValueError:
                try:
                    pub_date = datetime.strptime(earliest, "%Y-%m")
                except ValueError:
                    continue
            if date_start <= pub_date <= date_end:
                hits_list.append(hit)

        papers = []
        for hit in hits_list:
            metadata = hit.get("metadata", {})
            arxiv_eprints = metadata.get("arxiv_eprints", [])
            if not arxiv_eprints:
                continue

            # Count how many of our refs this paper cites
            paper_refs = metadata.get("references", [])
            paper_ref_ids = set()
            for ref in paper_refs:
                record = ref.get("record", {})
                ref_url = record.get("$ref", "")
                if "/literature/" in ref_url:
                    paper_ref_ids.add(ref_url.split("/literature/")[-1])

            shared_refs = len(set(ref_ids) & paper_ref_ids)

            papers.append({
                "arxiv_id": arxiv_eprints[0].get("value"),
                "title": metadata.get("titles", [{}])[0].get("title", ""),
                "authors": [a.get("full_name", "") for a in metadata.get("authors", [])[:10]],
                "num_authors": len(metadata.get("authors", [])),
                "shared_refs": shared_refs,
                "earliest_date": metadata.get("earliest_date", ""),
                "abstracts": metadata.get("abstracts", [{}])[0].get("value", ""),
                "categories": metadata.get("arxiv_categories", []),
            })

        return papers

    def search_papers_by_topic(
        self, keywords: List[str], months_start: int = 2, months_end: int = 12, max_results: int = 100
    ) -> List[dict]:
        """
        Search for papers matching topic keywords.
        This finds papers in the specific research area, not just those citing same refs.
        """
        from datetime import datetime, timedelta

        now = datetime.now()
        date_start = now - timedelta(days=months_end * 30)
        date_end = now - timedelta(days=months_start * 30)

        papers = []
        seen_arxiv = set()

        # Build search queries - use exact phrases for precision
        search_queries = []
        for kw in keywords[:5]:
            kw_clean = kw.strip().lower()
            if not kw_clean or len(kw_clean) < 3:
                continue

            # For gravity-related keywords, search for the exact gravity phrase
            if "gravity" in kw_clean:
                search_queries.append(f'"{kw_clean}"')
                # Also add hyphenated version
                if " " in kw_clean:
                    search_queries.append(f'"{kw_clean.replace(" ", "-")}"')

            # For super-renormalizable, search multiple variations
            if "super-renormalizable" in kw_clean or "superrenormalizable" in kw_clean:
                search_queries.append('"super-renormalizable gravity"')
                search_queries.append('"superrenormalizable gravity"')
                search_queries.append('"higher derivative gravity"')
                search_queries.append('"higher-derivative gravity"')
                search_queries.append('"quadratic gravity"')
                search_queries.append('"nonlocal gravity"')

            # For other keywords, add as-is
            if "gravity" not in kw_clean:
                search_queries.append(f'"{kw_clean}"')

        # Remove duplicates
        search_queries = list(dict.fromkeys(search_queries))

        # Search INSPIRE
        for query in search_queries[:8]:
            # Search in title first (more precise)
            params = {
                "q": f't {query}',
                "size": 40,
                "sort": "mostrecent",
            }
            data = self._get("literature", params)

            if data and "hits" in data:
                for hit in data["hits"].get("hits", []):
                    metadata = hit.get("metadata", {})
                    arxiv_eprints = metadata.get("arxiv_eprints", [])
                    if not arxiv_eprints:
                        continue

                    arxiv_id = arxiv_eprints[0].get("value")
                    if arxiv_id in seen_arxiv:
                        continue

                    # Filter by date
                    earliest = metadata.get("earliest_date", "")
                    try:
                        pub_date = datetime.strptime(earliest, "%Y-%m-%d")
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(earliest, "%Y-%m")
                        except ValueError:
                            continue

                    if not (date_start <= pub_date <= date_end):
                        continue

                    seen_arxiv.add(arxiv_id)
                    papers.append({
                        "arxiv_id": arxiv_id,
                        "title": metadata.get("titles", [{}])[0].get("title", ""),
                        "authors": [a.get("full_name", "") for a in metadata.get("authors", [])[:10]],
                        "num_authors": len(metadata.get("authors", [])),
                        "shared_refs": 0,
                        "topic_match": True,
                        "earliest_date": earliest,
                        "abstracts": metadata.get("abstracts", [{}])[0].get("value", ""),
                        "categories": metadata.get("arxiv_categories", []),
                    })

            if len(papers) >= max_results:
                break

        return papers[:max_results]

    def find_citing_authors(
        self, arxiv_id: str, months_start: int = 2, months_end: int = 12
    ) -> List[dict]:
        """
        Find authors of papers that cite the target paper.
        These are people actively engaging with this work.
        """
        from datetime import datetime, timedelta

        now = datetime.now()
        date_start = now - timedelta(days=months_end * 30)
        date_end = now - timedelta(days=months_start * 30)

        # First get the INSPIRE record ID for this paper
        params = {
            "q": f"arxiv:{arxiv_id}",
            "size": 1,
        }
        data = self._get("literature", params)

        if not data or not data.get("hits", {}).get("hits"):
            return []

        record_id = data["hits"]["hits"][0].get("id")
        if not record_id:
            return []

        # Find papers citing this one
        params = {
            "q": f"citedrecid:{record_id} and date >= {date_start.strftime('%Y-%m-%d')} and date <= {date_end.strftime('%Y-%m-%d')}",
            "size": 100,
            "sort": "mostrecent",
        }
        citing_data = self._get("literature", params)

        if not citing_data or "hits" not in citing_data:
            return []

        authors_info = []
        for hit in citing_data["hits"].get("hits", []):
            metadata = hit.get("metadata", {})
            arxiv_eprints = metadata.get("arxiv_eprints", [])
            if not arxiv_eprints:
                continue

            for author in metadata.get("authors", [])[:5]:  # First 5 authors
                authors_info.append({
                    "name": author.get("full_name", ""),
                    "paper_arxiv": arxiv_eprints[0].get("value"),
                    "paper_title": metadata.get("titles", [{}])[0].get("title", ""),
                    "citing": True,
                })

        return authors_info
