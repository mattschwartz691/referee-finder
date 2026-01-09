from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


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

    def __hash__(self):
        return hash(self.arxiv_id)

    def __eq__(self, other):
        if isinstance(other, Paper):
            return self.arxiv_id == other.arxiv_id
        return False


@dataclass
class Author:
    """Represents an author with their INSPIRE record."""
    name: str
    inspire_id: Optional[str] = None
    orcid: Optional[str] = None
    institution: Optional[str] = None
    first_paper_year: Optional[int] = None
    recent_papers: List[Paper] = field(default_factory=list)
    collaborators_3yr: List[str] = field(default_factory=list)
    _rank_stage: Optional[str] = None  # Override from INSPIRE rank

    @property
    def career_years(self) -> Optional[int]:
        if self.first_paper_year:
            return datetime.now().year - self.first_paper_year
        return None

    @property
    def career_stage(self) -> Optional[str]:
        # Use INSPIRE rank if available
        if self._rank_stage:
            return self._rank_stage

        # Fall back to years-based calculation
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
