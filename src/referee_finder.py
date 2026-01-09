from typing import List, Dict
from collections import defaultdict
from datetime import datetime

from .models import Paper, RefereeCandidate
from .arxiv_client import ArxivClient
from .inspire_client import InspireClient
from .utils import extract_keywords, names_match, calculate_relevance_score


class RefereeFinder:
    """Main class for finding suitable referees using citation network analysis."""

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
        """
        Find suitable referee candidates using citation network analysis.

        Strategy:
        1. Get the paper's references from INSPIRE
        2. Find other papers that cite the same references (co-citation)
        3. Authors of co-citing papers are likely in the same field
        4. Rank by number of shared references and filter by career criteria
        """
        # Step 1: Fetch the target paper
        self.log(f"Fetching paper {arxiv_id}...")
        paper = self.arxiv.fetch_paper(arxiv_id)
        if not paper:
            raise ValueError(f"Could not fetch paper {arxiv_id}")

        self.log(f"Title: {paper.title}")
        self.log(f"Authors: {', '.join(paper.authors[:5])}{'...' if len(paper.authors) > 5 else ''}")
        self.log(f"Categories: {', '.join(paper.categories)}")

        # Step 2: Get references from INSPIRE
        self.log("\nAnalyzing citation network...")
        ref_ids = self.inspire.get_paper_references(arxiv_id)
        self.log(f"Found {len(ref_ids)} references in INSPIRE")

        # Step 3: Find papers that cite the same references (co-citation analysis)
        self.log(f"Finding papers that share references ({months_start}-{months_end} months ago)...")
        co_citing_papers = self.inspire.get_papers_citing_refs(
            ref_ids,
            months_start=months_start,
            months_end=months_end,
            max_results=300
        )
        self.log(f"Found {len(co_citing_papers)} potentially relevant papers")

        # Step 4: Collect candidate authors weighted by shared references
        self.log("\nCollecting candidate authors...")
        author_data: Dict[str, dict] = defaultdict(lambda: {
            "papers": [],
            "shared_refs_total": 0,
            "max_shared_refs": 0
        })

        for cp in co_citing_papers:
            # Skip papers with too many authors (likely collaborations)
            if cp["num_authors"] > 15:
                continue

            for author_name in cp["authors"]:
                # Skip if author is on the target paper
                if self._is_paper_author(author_name, paper.authors):
                    continue

                # Create Paper object for tracking
                try:
                    pub_date = datetime.strptime(cp["earliest_date"], "%Y-%m-%d")
                except ValueError:
                    try:
                        pub_date = datetime.strptime(cp["earliest_date"], "%Y-%m")
                    except ValueError:
                        pub_date = datetime.now()

                rel_paper = Paper(
                    arxiv_id=cp["arxiv_id"],
                    title=cp["title"],
                    abstract=cp.get("abstracts", ""),
                    authors=cp["authors"],
                    categories=cp.get("categories", []),
                    published=pub_date,
                    num_authors=cp["num_authors"]
                )

                author_data[author_name]["papers"].append(rel_paper)
                author_data[author_name]["shared_refs_total"] += cp["shared_refs"]
                author_data[author_name]["max_shared_refs"] = max(
                    author_data[author_name]["max_shared_refs"],
                    cp["shared_refs"]
                )

        self.log(f"Found {len(author_data)} unique potential referees")

        # Step 5: Filter and rank candidates
        self.log("\nEvaluating candidates...")
        candidates = []
        evaluated = 0
        skipped_reasons = defaultdict(int)

        # Sort by total shared references (most relevant first)
        sorted_authors = sorted(
            author_data.items(),
            key=lambda x: (x[1]["shared_refs_total"], len(x[1]["papers"])),
            reverse=True
        )

        for author_name, data in sorted_authors:
            if len(candidates) >= num_candidates * 3:
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

            # Get publication counts (don't filter on inactive since they have relevant papers)
            papers_3yr, small_collab_counts = self.inspire.get_author_papers_with_counts(
                author_name, years=3, max_results=100
            )

            # Store publication activity
            author_info.small_collab_papers_by_year = small_collab_counts
            author_info.recent_papers = data["papers"]

            # Calculate relevance score based on shared references
            # Higher score = more shared references with target paper
            max_possible_refs = min(len(ref_ids), 10)  # We sample up to 10 refs
            ref_score = data["shared_refs_total"] / max(max_possible_refs * len(data["papers"]), 1)
            paper_count_bonus = min(len(data["papers"]) * 0.1, 0.3)
            relevance = min(ref_score + paper_count_bonus, 1.0)

            candidate = RefereeCandidate(
                author=author_info,
                relevant_papers=data["papers"],
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

            lines.append(f"   Career: {author.career_info_str}")
            if author.career_stage:
                lines.append(f"   Stage: {author.career_stage}")

            lines.append(f"   Papers (<10 authors): {author.publication_activity_str}")
            lines.append(f"   Relevance Score: {candidate.relevance_score:.2f}")

            if candidate.relevant_papers:
                lines.append("   Relevant Papers (share references with target):")
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
