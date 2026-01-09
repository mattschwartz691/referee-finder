import re
import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from .models import Paper


class ArxivClient:
    """Client for interacting with arXiv API."""

    CATEGORIES = ["hep-ph", "hep-th"]

    def __init__(self):
        self.client = arxiv.Client()

    def normalize_arxiv_id(self, arxiv_id: str) -> str:
        """Normalize arXiv ID to standard format."""
        arxiv_id = arxiv_id.strip()
        arxiv_id = re.sub(r'^(https?://)?(www\.)?arxiv\.org/(abs|pdf)/', '', arxiv_id)
        arxiv_id = arxiv_id.replace('.pdf', '')
        arxiv_id = re.sub(r'^arXiv:', '', arxiv_id, flags=re.IGNORECASE)
        return arxiv_id

    def fetch_paper(self, arxiv_id: str) -> Optional[Paper]:
        """Fetch a paper by arXiv ID."""
        arxiv_id = self.normalize_arxiv_id(arxiv_id)
        search = arxiv.Search(id_list=[arxiv_id])

        try:
            results = list(self.client.results(search))
            if not results:
                return None

            result = results[0]
            return Paper(
                arxiv_id=result.entry_id.split('/')[-1].split('v')[0],
                title=result.title,
                abstract=result.summary,
                authors=[author.name for author in result.authors],
                categories=result.categories,
                published=result.published
            )
        except Exception as e:
            print(f"Error fetching paper {arxiv_id}: {e}")
            return None

    def search_similar_papers(
        self,
        categories: List[str],
        keywords: List[str],
        months_ago_start: int = 2,
        months_ago_end: int = 12,
        max_results: int = 200
    ) -> List[Paper]:
        """
        Search for similar papers in given categories within date range.

        Args:
            categories: arXiv categories to search (e.g., ['hep-ph', 'hep-th'])
            keywords: Keywords to search for in title/abstract
            months_ago_start: Papers must be at least this many months old
            months_ago_end: Papers must be at most this many months old
            max_results: Maximum number of papers to return
        """
        now = datetime.now(timezone.utc)
        date_start = now - timedelta(days=months_ago_end * 30)
        date_end = now - timedelta(days=months_ago_start * 30)

        # Build category query
        cat_query = " OR ".join([f"cat:{cat}" for cat in categories])

        # Build keyword query - search in title and abstract
        if keywords:
            # Use most significant keywords
            kw_terms = []
            for kw in keywords[:5]:  # Limit to top 5 keywords
                kw_clean = kw.strip().lower()
                if len(kw_clean) > 2:
                    kw_terms.append(f'(ti:"{kw_clean}" OR abs:"{kw_clean}")')

            if kw_terms:
                kw_query = " OR ".join(kw_terms)
                query = f"({cat_query}) AND ({kw_query})"
            else:
                query = f"({cat_query})"
        else:
            query = f"({cat_query})"

        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        papers = []
        try:
            for result in self.client.results(search):
                pub_date = result.published
                if date_start <= pub_date <= date_end:
                    paper = Paper(
                        arxiv_id=result.entry_id.split('/')[-1].split('v')[0],
                        title=result.title,
                        abstract=result.summary,
                        authors=[author.name for author in result.authors],
                        categories=result.categories,
                        published=pub_date
                    )
                    papers.append(paper)
        except Exception as e:
            print(f"Error searching papers: {e}")

        return papers

    def get_date_range(
        self, months_ago_start: int = 2, months_ago_end: int = 12
    ) -> Tuple[datetime, datetime]:
        """Get date range for filtering papers."""
        now = datetime.now(timezone.utc)
        return (
            now - timedelta(days=months_ago_end * 30),
            now - timedelta(days=months_ago_start * 30)
        )
