"""Generate a synthetic fake-home tree for demos/tests.

Thin CLI wrapper around `token_finops_cli.synth.generate` -- see that module
(and `docs/SYNTH.md`) for what gets written per tool and what the scenarios
mean. Equivalent to `token-finops synth`.
"""
import argparse

from token_finops_cli.synth import ALL_TOOLS, generate
from token_finops_cli.synth.env import env_for
from token_finops_cli.synth.scenarios import KNOWN as SCENARIOS


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", help="Output directory for the synthetic fake-home tree")
    parser.add_argument("--tools", action="append", default=None,
                        help=f"comma-separated tool(s) to generate (default: all). known: {', '.join(ALL_TOOLS)}")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--scenario", choices=SCENARIOS, default="steady")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--print-env", action="store_true",
                        help="also print `export VAR=...` lines")
    args = parser.parse_args()

    tools = None
    if args.tools:
        tools = [t.strip() for chunk in args.tools for t in chunk.split(",") if t.strip()]

    manifest = generate(args.out, tools=tools, days=args.days, scenario=args.scenario, seed=args.seed)
    for tool, info in manifest.items():
        print(f"{tool}: {info['events']} events -> {info['path']}")
    if args.print_env:
        for var, val in env_for(args.out).items():
            print(f"export {var}={val}")


if __name__ == "__main__":
    main()
