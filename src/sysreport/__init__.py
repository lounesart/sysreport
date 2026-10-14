"""sysreport: read-only health report for a Linux workstation."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table

from sysreport import mentor
from sysreport.checks import ALL_CHECKS, Result, Status

__version__ = "0.2.0"

STYLE = {
    Status.OK: ("[green]✔ ok[/]", "green"),
    Status.WARN: ("[yellow]▲ warn[/]", "yellow"),
    Status.FAIL: ("[bold red]✖ fail[/]", "red"),
    Status.SKIP: ("[dim]– skip[/]", "dim"),
}


def collect() -> list[Result]:
    results = []
    for check in ALL_CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 (one broken check shouldn't hide the rest)
            results.append(Result(check.__name__, Status.SKIP, f"error: {exc}"))
    return results


def exit_code(results: list[Result]) -> int:
    """0 = all good, 1 = warnings, 2 = failures (useful in scripts and timers)."""
    statuses = {r.status for r in results}
    if Status.FAIL in statuses:
        return 2
    if Status.WARN in statuses:
        return 1
    return 0


def render(results: list[Result], console: Console) -> None:
    table = Table(title="sysreport", title_style="bold", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Details")
    for r in results:
        label, color = STYLE[r.status]
        table.add_row(r.name, label, f"[{color}]{r.detail}[/]")
    console.print(table)
    counts = {s: sum(r.status is s for r in results) for s in Status}
    console.print(
        f"[green]{counts[Status.OK]} ok[/] · [yellow]{counts[Status.WARN]} warn[/] · "
        f"[red]{counts[Status.FAIL]} fail[/] · [dim]{counts[Status.SKIP]} skipped[/]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sysreport", description="Read-only health report for your Linux machine."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print results as JSON")
    mode.add_argument(
        "--explain",
        action="store_true",
        help="explain every problem and the commands that fix it (runs nothing)",
    )
    mode.add_argument(
        "--fix",
        action="store_true",
        help="guided fix: walk through each command and ask before running it",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args(argv)

    if args.fix and not sys.stdin.isatty():
        parser.error("--fix is interactive and needs a terminal (try --explain)")

    console = Console()
    results = collect()
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
        return exit_code(results)

    render(results, console)
    if args.explain or args.fix:
        console.print()
        (mentor.fix if args.fix else mentor.explain)(results, console)
    elif mentor.problems(results):
        console.print("[dim]Run sysreport --fix to go through these step by step.[/]")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
