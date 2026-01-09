"""
EJPC Referee Finder - Web Interface

Run with: streamlit run app.py
"""

import streamlit as st
from src.referee_finder import RefereeFinder

st.set_page_config(
    page_title="EJPC Referee Finder",
    page_icon="📚",
    layout="wide"
)

st.title("EJPC Referee Finder")
st.markdown("Find suitable referees for physics papers using citation network analysis")

# Sidebar settings
st.sidebar.header("Settings")
num_candidates = st.sidebar.slider("Number of candidates", 3, 15, 5)
months_start = st.sidebar.slider("Papers at least N months old", 1, 6, 2)
months_end = st.sidebar.slider("Papers at most N months old", 6, 24, 18)

# Main input
arxiv_id = st.text_input(
    "Enter arXiv ID or URL",
    placeholder="e.g., 2401.12345 or https://arxiv.org/abs/2401.12345"
)

if st.button("Find Referees", type="primary"):
    if not arxiv_id.strip():
        st.error("Please enter an arXiv ID")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            finder = RefereeFinder(verbose=False)

            status_text.text("Fetching paper from arXiv...")
            progress_bar.progress(10)

            paper = finder.arxiv.fetch_paper(arxiv_id)
            if not paper:
                st.error(f"Could not fetch paper: {arxiv_id}")
                st.stop()

            # Display paper info
            st.subheader("Paper Details")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Title:** {paper.title}")
                st.markdown(f"**Authors:** {', '.join(paper.authors[:5])}{'...' if len(paper.authors) > 5 else ''}")
            with col2:
                st.markdown(f"**Categories:** {', '.join(paper.categories)}")
                st.markdown(f"**arXiv:** [{paper.arxiv_id}](https://arxiv.org/abs/{paper.arxiv_id})")

            status_text.text("Analyzing citation network and evaluating candidates...")
            progress_bar.progress(30)

            candidates = finder.find_referees(
                arxiv_id=arxiv_id,
                num_candidates=num_candidates,
                months_start=months_start,
                months_end=months_end
            )

            progress_bar.progress(100)
            status_text.text("Done!")

            # Display results
            st.subheader(f"Referee Candidates ({len(candidates)} found)")

            if not candidates:
                st.warning("No suitable referee candidates found. Try broadening the date range in settings.")
            else:
                for i, candidate in enumerate(candidates, 1):
                    author = candidate.author
                    header = f"**{i}. {author.name}** - {author.career_stage or 'Unknown'} (score: {candidate.relevance_score:.2f})"
                    with st.expander(header, expanded=(i <= 3)):
                        col1, col2 = st.columns([2, 1])

                        with col1:
                            if author.institution:
                                st.markdown(f"**Institution:** {author.institution}")

                            # Career details
                            st.markdown(f"**Career:** {author.career_info_str}")

                            # Publication activity
                            st.markdown(f"**Papers (<10 authors):** {author.publication_activity_str}")

                            # Relevant papers with dates
                            st.markdown("**Papers sharing references with target:**")
                            for p in candidate.relevant_papers[:3]:
                                title_short = p.title[:70] + "..." if len(p.title) > 70 else p.title
                                st.markdown(f"- [{title_short}](https://arxiv.org/abs/{p.arxiv_id}) ({p.pub_date_str})")

                        with col2:
                            st.markdown(f"**Relevance Score:** {candidate.relevance_score:.2f}")
                            if author.orcid:
                                st.markdown(f"**ORCID:** [{author.orcid}](https://orcid.org/{author.orcid})")
                            if author.inspire_id:
                                st.markdown(f"**INSPIRE:** [Profile](https://inspirehep.net/authors/{author.inspire_id})")

        except Exception as e:
            st.error(f"Error: {str(e)}")
        finally:
            progress_bar.empty()
            status_text.empty()

# Footer
st.markdown("---")
st.markdown(
    "Built with [arXiv API](https://arxiv.org/help/api) and "
    "[INSPIRE-HEP API](https://inspirehep.net/help/knowledge-base/inspire-api)"
)
