"""CLI wrapper for building a synthetic Copilot session-store.db (demos/tests).

See token_finops_cli.examples_helper.build_synthetic_db for the actual
generation logic - kept in the package so tests can import it too.
"""
import argparse

from token_finops_cli.examples_helper import build_synthetic_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Output path for the synthetic .db file")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--events-per-day", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    n = build_synthetic_db(args.path, args.days, args.events_per_day, args.seed)
    print(f"Wrote {n} synthetic events to {args.path}")


if __name__ == "__main__":
    main()
