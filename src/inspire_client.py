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
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
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
