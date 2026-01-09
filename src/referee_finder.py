from typing import List, Dict
from collections import defaultdict
from datetime import datetime
import re

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

    def _extract_topic_keywords(self, title: str, abstract: str, niche_only: bool = False) -> List[str]:
        """
        Extract specific topic keywords from paper title/abstract.
        Focus on the SUBJECT MATTER (physics topics) over METHODS/TECHNIQUES.

        Args:
            niche_only: If True, only return distinctive topic keywords (no methods)

        Returns: List of keywords, with topics first and methods second (unless niche_only)
        """
        text = f"{title} {abstract}".lower()

        # Priority 1: Subject matter / physics topics (what the paper is ABOUT)
        # These are the NICHE topics that define the specific research area
        topic_patterns = [
            # Gravity theories - high priority
            (r'\b(super-?renormalizable)\s*(gravity)?\b', 'super-renormalizable gravity'),
            (r'\b(higher[- ]derivative)\s+(gravity|theories?)\b', 'higher derivative gravity'),
            (r'\b(non-?local)\s+(gravity|theories?)\b', 'nonlocal gravity'),
            (r'\b(modified)\s+(gravity|gr)\b', 'modified gravity'),
            (r'\b(quadratic)\s+(gravity|curvature)\b', 'quadratic gravity'),
            (r'\b(ghost-?free)\s+(gravity)?\b', 'ghost-free gravity'),
            (r'\b(infinite[- ]derivative)\s+(gravity)?\b', 'infinite derivative gravity'),
            (r'\b(f\(r\)|f\(R\))\s*(gravity)?\b', 'f(R) gravity'),
            # Cosmology
            (r'\b(dark)\s+(matter|energy)\b', None),
            (r'\b(inflation|inflationary)\b', None),
            (r'\b(cosmological)\s+(perturbations?|constant)\b', None),
            # Particles / BSM
            (r'\b(higgs)\s+(boson|mechanism|sector)\b', None),
            (r'\b(supersymm\w+|susy)\b', 'supersymmetry'),
            (r'\b(beyond)\s+(the)?\s*(standard)\s+(model)\b', 'beyond standard model'),
        ]

        # Priority 2: Broad topics that many researchers work on (less niche)
        broad_topic_patterns = [
            (r'\b(quantum)\s+(gravity)\b', 'quantum gravity'),
            (r'\b(black)\s+(hole|holes)\b', 'black holes'),
            (r'\b(kerr)\s+(metric|black hole)?\b', 'Kerr'),
            (r'\b(newtonian)\s+(potential|limit)\b', 'Newtonian potential'),
        ]

        # Priority 3: Methods / techniques (how they study it - less important for finding niche referees)
        method_patterns = [
            r'\b(scattering)\s+(amplitudes?)\b',
            r'\b(on-?shell)\s+(methods?|amplitudes?)\b',
            r'\b(effective)\s+(field)\s+(theory|theories)\b',
            r'\b(renormalization)\s+(group)\b',
            r'\b(loop)\s+(corrections?|integrals?)\b',
            r'\b(feynman)\s+(diagrams?|rules?)\b',
        ]

        # Extract niche topic keywords (highest priority)
        niche_keywords = []
        for pattern, replacement in topic_patterns:
            if re.search(pattern, text):
                if replacement:
                    niche_keywords.append(replacement)
                else:
                    match = re.search(pattern, text)
                    if match:
                        kw = " ".join(g for g in match.groups() if g).strip()
                        if kw:
                            niche_keywords.append(kw)

        # Extract broad topic keywords
        broad_keywords = []
        for pattern, replacement in broad_topic_patterns:
            if re.search(pattern, text):
                if replacement:
                    broad_keywords.append(replacement)
                else:
                    match = re.search(pattern, text)
                    if match:
                        kw = " ".join(g for g in match.groups() if g).strip()
                        if kw:
                            broad_keywords.append(kw)

        # Extract method keywords
        method_keywords = []
        for pattern in method_patterns:
            if re.search(pattern, text):
                match = re.search(pattern, text)
                if match:
                    kw = " ".join(g for g in match.groups() if g).strip()
                    if kw:
                        method_keywords.append(kw)

        # Also extract key noun phrases from title focusing on the subject
        title_lower = title.lower()

        # Look for "X in Y" pattern where Y is the subject
        in_match = re.search(r'in\s+([^,]+)$', title_lower)
        if in_match:
            subject = in_match.group(1).strip()
            if len(subject.split()) <= 4:
                niche_keywords.insert(0, subject)  # High priority

        # If niche_only, return only the distinctive topic keywords
        if niche_only:
            keywords = list(dict.fromkeys(niche_keywords))  # Remove duplicates
            self.log(f"  Using niche-only keywords: {keywords}")
            return keywords[:8] if keywords else broad_keywords[:4]

        # Combine: niche topics first, then broad topics, then methods
        all_keywords = list(dict.fromkeys(niche_keywords + broad_keywords + method_keywords))
        return all_keywords[:8]

    def find_referees(
        self,
        arxiv_id: str,
        num_candidates: int = 5,
        months_start: int = 2,
        months_end: int = 12,
        topic_weight: float = 1.0,
        citation_weight: float = 1.0,
        niche_only: bool = False
    ) -> List[RefereeCandidate]:
        """
        Find suitable referee candidates using hybrid approach:
        1. Co-citation analysis (papers citing same references)
        2. Topic keyword search (papers on same specific topic)
        3. Filter by career criteria and mainstream level matching

        Args:
            topic_weight: Weight for topic-matched papers (0-2, default 1.0)
            citation_weight: Weight for co-citation papers (0-2, default 1.0)
            niche_only: If True, only use niche topic keywords (exclude methods like 'scattering amplitudes')
        """
        # Step 1: Fetch the target paper
        self.log(f"Fetching paper {arxiv_id}...")
        paper = self.arxiv.fetch_paper(arxiv_id)
        if not paper:
            raise ValueError(f"Could not fetch paper {arxiv_id}")

        self.log(f"Title: {paper.title}")
        self.log(f"Authors: {', '.join(paper.authors[:5])}{'...' if len(paper.authors) > 5 else ''}")
        self.log(f"Categories: {', '.join(paper.categories)}")

        # Step 1.5: Extract topic keywords FIRST (needed for reference classification)
        topic_keywords = self._extract_topic_keywords(paper.title, paper.abstract, niche_only=niche_only)
        self.log(f"\nTopic keywords: {', '.join(topic_keywords[:5])}")

        # Step 1.6: Calculate mainstream index for target paper
        self.log("\nCalculating mainstream index...")
        target_mainstream, mainstream_details = self.inspire.calculate_mainstream_index(arxiv_id)
        paper.mainstream_index = target_mainstream
        self.log(f"Mainstream index: {target_mainstream:.2f} (avg ref citations: {mainstream_details.get('avg_ref_citations', 'N/A')})")

        # Step 2: Get references from INSPIRE, separated by topic
        self.log("\nAnalyzing citation network...")
        topic_refs, method_refs = self.inspire.get_paper_references_by_topic(arxiv_id, topic_keywords)
        all_refs = topic_refs + method_refs
        self.log(f"Found {len(all_refs)} references ({len(topic_refs)} topic-specific, {len(method_refs)} methods)")

        # Step 3a: Find papers that cite the topic-specific references (prioritized)
        self.log(f"Finding papers that cite topic-specific references ({months_start}-{months_end} months ago)...")
        co_citing_papers = []

        if topic_refs:
            # First, find papers citing topic-specific references (these are the most relevant)
            topic_citing = self.inspire.get_papers_citing_refs(
                topic_refs,
                months_start=months_start,
                months_end=months_end,
                max_results=150
            )
            # Double the shared_refs weight for topic refs, but DON'T mark as topic_match
            # (topic_match is reserved for papers found via keyword search)
            for p in topic_citing:
                p["shared_refs"] = p.get("shared_refs", 0) * 2  # Double weight for topic refs
                # topic_match stays False - this is co-citation, not keyword match
            co_citing_papers.extend(topic_citing)
            self.log(f"Found {len(topic_citing)} papers citing topic-specific references")

        # Also include papers citing method references, but with lower weight
        if method_refs and len(co_citing_papers) < 100:
            method_citing = self.inspire.get_papers_citing_refs(
                method_refs,
                months_start=months_start,
                months_end=months_end,
                max_results=100
            )
            co_citing_papers.extend(method_citing)
            self.log(f"Found {len(method_citing)} papers citing method references")

        self.log(f"Total co-citing papers: {len(co_citing_papers)}")

        # Step 3b: Search by topic keywords
        topic_papers = []
        if topic_keywords:
            self.log("Searching for papers by topic...")
            topic_papers = self.inspire.search_papers_by_topic(
                topic_keywords,
                months_start=months_start,
                months_end=months_end,
                max_results=100
            )
            self.log(f"Found {len(topic_papers)} topic-matched papers")

        # Combine both sources
        all_papers = co_citing_papers + topic_papers
        self.log(f"Total candidate papers: {len(all_papers)}")

        # Step 4: Collect candidate authors weighted by shared references AND topic match
        self.log("\nCollecting candidate authors...")
        author_data: Dict[str, dict] = defaultdict(lambda: {
            "papers": [],
            "shared_refs_total": 0,
            "max_shared_refs": 0,
            "topic_match_count": 0,  # Papers found via topic search
        })

        seen_papers = set()  # Avoid double-counting papers in both lists
        for cp in all_papers:
            # Skip papers with too many authors (likely collaborations)
            if cp["num_authors"] > 15:
                continue

            # Skip duplicate papers
            if cp["arxiv_id"] in seen_papers:
                continue
            seen_papers.add(cp["arxiv_id"])

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
                author_data[author_name]["shared_refs_total"] += cp.get("shared_refs", 0)
                author_data[author_name]["max_shared_refs"] = max(
                    author_data[author_name]["max_shared_refs"],
                    cp.get("shared_refs", 0)
                )
                # Track topic matches (more valuable for niche papers)
                if cp.get("topic_match"):
                    author_data[author_name]["topic_match_count"] += 1

        self.log(f"Found {len(author_data)} unique potential referees")

        # Step 5: Filter and rank candidates
        self.log("\nEvaluating candidates...")
        self.log(f"Using weights: topic={topic_weight:.1f}, citation={citation_weight:.1f}, niche_only={niche_only}")
        candidates = []
        evaluated = 0
        skipped_reasons = defaultdict(int)

        # Sort by combined score using the provided weights
        # In niche_only mode, heavily prioritize topic matches over co-citation
        if niche_only:
            # In niche mode, topic match is critical - authors must have topic-matched papers
            effective_topic_weight = topic_weight * 3.0  # Triple the weight
            effective_citation_weight = citation_weight * 0.2  # Reduce citation weight
        else:
            # Normal mode: adjust based on mainstream index
            niche_boost = 1.0 - target_mainstream
            effective_topic_weight = topic_weight * (1 + niche_boost)
            effective_citation_weight = citation_weight

        sorted_authors = sorted(
            author_data.items(),
            key=lambda x: (
                x[1]["topic_match_count"] * effective_topic_weight +  # Topic matches (heavily weighted in niche mode)
                x[1]["shared_refs_total"] * effective_citation_weight * 0.5 +   # Shared refs
                len(x[1]["papers"]) * 0.1                              # Paper count
            ),
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

            # Calculate relevance score based on:
            # 1. Shared references with target paper
            # 2. Topic match bonus (papers found via keyword search)
            # 3. Paper count bonus
            max_possible_refs = min(len(all_refs), 10)  # We sample up to 10 refs
            ref_score = data["shared_refs_total"] / max(max_possible_refs * len(data["papers"]), 1)
            topic_bonus = min(data["topic_match_count"] * 0.2, 0.4)  # Up to 0.4 for topic matches
            paper_count_bonus = min(len(data["papers"]) * 0.1, 0.2)
            relevance = min(ref_score + topic_bonus + paper_count_bonus, 1.0)

            # Store mainstream index for display
            author_info.mainstream_index = target_mainstream  # Will update with author's own value later

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
