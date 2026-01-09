from typing import List
from collections import defaultdict

from .models import Paper, RefereeCandidate
from .arxiv_client import ArxivClient
from .inspire_client import InspireClient
from .utils import extract_keywords, names_match, calculate_relevance_score


class RefereeFinder:
    """Main class for finding suitable referees."""

    def __init__(self, verbose: bool = True):
        self.arxiv = ArxivClient()
        self.inspire = InspireClient()
        self.verbose = verbose

    def log(self, message: str):
        if self.verbose:
            print(message)

    def find_referees(
        self,
        arxiv_id: str,
        num_candidates: int = 5,
        months_start: int = 2,
        months_end: int = 12
    ) -> List[RefereeCandidate]:
        # Step 1: Fetch the target paper
        self.log(f"Fetching paper {arxiv_id}...")
        paper = self.arxiv.fetch_paper(arxiv_id)
        if not paper:
            raise ValueError(f"Could not fetch paper {arxiv_id}")

        self.log(f"Title: {paper.title}")
        self.log(f"Authors: {', '.join(paper.authors[:5])}...")
        self.log(f"Categories: {', '.join(paper.categories)}")

        # Step 2: Extract keywords
        keywords = extract_keywords(paper.title, paper.abstract)
        self.log(f"Keywords: {', '.join(keywords[:5])}...")

        # Step 3: Search for similar papers
        self.log(f"\nSearching for similar papers ({months_start}-{months_end} months ago)...")
        categories = [c for c in paper.categories if c in ["hep-ph", "hep-th"]]
        if not categories:
            categories = ["hep-ph", "hep-th"]

        similar_papers = self.arxiv.search_similar_papers(
            categories=categories,
            keywords=keywords,
            months_ago_start=months_start,
            months_ago_end=months_end,
            max_results=200
        )
        self.log(f"Found {len(similar_papers)} potentially relevant papers")

        # Step 4: Collect candidate authors
        self.log("\nCollecting candidate authors...")
        author_papers = defaultdict(list)
        for sim_paper in similar_papers:
            for author in sim_paper.authors:
                if not self._is_paper_author(author, paper.authors):
                    author_papers[author].append(sim_paper)

        self.log(f"Found {len(author_papers)} unique potential referees")

        # Step 5: Filter and rank candidates
        self.log("\nEvaluating candidates...")
        candidates = []
        evaluated = 0
        skipped_reasons = defaultdict(int)

        sorted_authors = sorted(
            author_papers.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        for author_name, relevant_papers in sorted_authors:
            if len(candidates) >= num_candidates * 2:
                break

            evaluated += 1
            if evaluated % 10 == 0:
                self.log(f"  Evaluated {evaluated} candidates...")

            # Get author info from INSPIRE
            author_info = self.inspire.get_author_info(author_name)
            if not author_info:
                skipped_reasons["not_found_inspire"] += 1
                continue

            # Check career stage
            if not author_info.career_stage:
                skipped_reasons["unknown_career"] += 1
                continue

            if author_info.career_stage not in ["Postdoc", "Junior Faculty", "Mid-Career"]:
                skipped_reasons[f"career_{author_info.career_stage.lower()}"] += 1
                continue

            # Check for conflicts with paper authors
            has_conflict = self.inspire.check_collaboration(
                author_name, paper.authors, years=3
            )
            if has_conflict:
                skipped_reasons["conflict"] += 1
                continue

            # Check if still active and get publication counts
            papers_3yr, small_collab_counts = self.inspire.get_author_papers_with_counts(
                author_name, years=3, max_results=100
            )
            if not papers_3yr:
                skipped_reasons["inactive"] += 1
                continue

            # Store publication activity
            author_info.small_collab_papers_by_year = small_collab_counts
            author_info.recent_papers = relevant_papers

            # Calculate relevance score
            relevance = calculate_relevance_score(
                relevant_papers, keywords, paper.categories
            )

            candidate = RefereeCandidate(
                author=author_info,
                relevant_papers=relevant_papers,
                relevance_score=relevance
            )
            candidates.append(candidate)

        self.log(f"\nFound {len(candidates)} eligible candidates")
        if skipped_reasons:
            self.log("Skipped reasons:")
            for reason, count in sorted(skipped_reasons.items(), key=lambda x: -x[1]):
                self.log(f"  {reason}: {count}")

        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:num_candidates]

    def _is_paper_author(self, candidate: str, paper_authors: List[str]) -> bool:
        for author in paper_authors:
            if names_match(candidate, author):
                return True
        return False

    def format_results(self, candidates: List[RefereeCandidate], arxiv_id: str) -> str:
        lines = []
        lines.append(f"\n{'='*70}")
        lines.append(f"Referee Candidates for arXiv:{arxiv_id}")
        lines.append(f"{'='*70}\n")

        for i, candidate in enumerate(candidates, 1):
            author = candidate.author
            lines.append(f"{i}. {author.name}")
            if author.institution:
                lines.append(f"   Institution: {author.institution}")

            # Career info: PhD year, first pub, etc.
            lines.append(f"   Career: {author.career_info_str}")
            if author.career_stage:
                lines.append(f"   Stage: {author.career_stage}")

            # Publication activity (papers with <10 authors)
            lines.append(f"   Papers (<10 authors): {author.publication_activity_str}")

            lines.append(f"   Relevance Score: {candidate.relevance_score:.2f}")

            if candidate.relevant_papers:
                lines.append("   Relevant Papers:")
                for paper in candidate.relevant_papers[:3]:
                    title_short = paper.title[:55] + "..." if len(paper.title) > 55 else paper.title
                    lines.append(f"   - \"{title_short}\"")
                    lines.append(f"     ({paper.pub_date_str}, arXiv:{paper.arxiv_id})")

            if author.orcid:
                lines.append(f"   ORCID: {author.orcid}")
            if author.inspire_id:
                lines.append(f"   INSPIRE: https://inspirehep.net/authors/{author.inspire_id}")

            lines.append("")

        return "\n".join(lines)
