from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict


@dataclass
class Paper:
    """Represents a paper from arXiv or INSPIRE."""
    arxiv_id: str
    title: str
    abstract: str
    authors: List[str]
    categories: List[str]
    published: datetime
    inspire_id: Optional[str] = None
    num_authors: int = 0

    def __hash__(self):
        return hash(self.arxiv_id)

    def __eq__(self, other):
        if isinstance(other, Paper):
            return self.arxiv_id == other.arxiv_id
        return False

    @property
    def pub_date_str(self) -> str:
        """Return formatted publication date (e.g., 'Mar 2024')."""
        return self.published.strftime("%b %Y")


@dataclass
class Author:
    """Represents an author with their INSPIRE record."""
    name: str
    inspire_id: Optional[str] = None
    orcid: Optional[str] = None
    institution: Optional[str] = None
    first_paper_year: Optional[int] = None
    phd_year: Optional[int] = None
    phd_institution: Optional[str] = None
    recent_papers: List[Paper] = field(default_factory=list)
    collaborators_3yr: List[str] = field(default_factory=list)
    _rank_stage: Optional[str] = None
    # Papers with <10 authors per year: {2024: 5, 2025: 3, 2026: 1}
    small_collab_papers_by_year: Dict[int, int] = field(default_factory=dict)

    @property
    def career_years(self) -> Optional[int]:
        if self.first_paper_year:
            return datetime.now().year - self.first_paper_year
        return None

    @property
    def career_stage(self) -> Optional[str]:
        if self._rank_stage:
            return self._rank_stage

        years = self.career_years
        if years is None:
            return None
        if 2 <= years <= 5:
            return "Postdoc"
        elif 5 < years <= 10:
            return "Junior Faculty"
        elif 10 < years <= 20:
            return "Mid-Career"
        elif years < 2:
            return "Graduate Student"
        else:
            return "Senior"

    @property
    def career_info_str(self) -> str:
        """Return formatted career information string."""
        parts = []
        if self.phd_year:
            phd_str = f"PhD {self.phd_year}"
            if self.phd_institution:
                phd_str += f" ({self.phd_institution})"
            parts.append(phd_str)
        if self.first_paper_year:
            parts.append(f"First pub {self.first_paper_year}")
        if not parts:
            return "Career info unavailable"
        return ", ".join(parts)

    @property
    def publication_activity_str(self) -> str:
        """Return publication counts for last 3 years (papers with <10 authors)."""
        current_year = datetime.now().year
        years = [current_year, current_year - 1, current_year - 2]
        counts = []
        for y in years:
            count = self.small_collab_papers_by_year.get(y, 0)
            counts.append(f"{y}: {count}")
        return ", ".join(counts)


@dataclass
class RefereeCandidate:
    """A potential referee with relevance scoring."""
    author: Author
    relevant_papers: List[Paper] = field(default_factory=list)
    relevance_score: float = 0.0

    @property
    def is_eligible(self) -> bool:
        """Check if candidate meets all criteria."""
        stage = self.author.career_stage
        return stage in ["Postdoc", "Junior Faculty", "Mid-Career"]
