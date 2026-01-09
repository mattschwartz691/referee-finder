#!/usr/bin/env python3
"""
EJPC Referee Finder

A tool to find suitable referees for physics papers by searching
arXiv and INSPIRE-HEP databases.

Usage:
    python -m src.main <arxiv_id> [--num N] [--quiet]
    python -m src.main 2401.12345
    python -m src.main https://arxiv.org/abs/2401.12345
"""

import argparse
import sys
from pathlib import Path

from .referee_finder import RefereeFinder


def main():
    parser = argparse.ArgumentParser(
        description="Find suitable referees for a physics paper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m src.main 2401.12345
    python -m src.main 2401.12345 --num 10
    python -m src.main https://arxiv.org/abs/2401.12345 --quiet
        """
    )
    parser.add_argument(
        "arxiv_id",
        help="arXiv identifier (e.g., 2401.12345) or full URL"
    )
    parser.add_argument(
        "--num", "-n",
        type=int,
        default=5,
        help="Number of referee candidates to return (default: 5)"
    )
    parser.add_argument(
        "--months-start",
        type=int,
        default=2,
        help="Minimum months ago for related papers (default: 2)"
    )
    parser.add_argument(
        "--months-end",
        type=int,
        default=12,
        help="Maximum months ago for related papers (default: 12)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress messages"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Save results to file"
    )

    args = parser.parse_args()

    try:
        finder = RefereeFinder(verbose=not args.quiet)

        candidates = finder.find_referees(
            arxiv_id=args.arxiv_id,
            num_candidates=args.num,
            months_start=args.months_start,
            months_end=args.months_end
        )

        if not candidates:
            print("\nNo suitable referee candidates found.")
            print("Try broadening the search with --months-end 18")
            sys.exit(1)

        # Format and display results
        results = finder.format_results(candidates, args.arxiv_id)
        print(results)

        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(results)
            print(f"\nResults saved to: {output_path}")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nSearch cancelled.")
        sys.exit(130)


if __name__ == "__main__":
    main()
