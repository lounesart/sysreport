"""Guided fix mode: explain each problem, then go through the fix commands one by one."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from sysreport.checks import CHECKS_BY_KEY, Result, Status
from sysreport.guides import Guide, Step, guide_for

Ask = Callable[[str], str]
Runner = Callable[[list[str]], int]


def default_ask(question: str) -> str:
    return Prompt.ask(question, choices=["r", "s", "q"], default="s")


def default_runner(cmd: list[str]) -> int:
    """Run with the user's terminal attached, so sudo can ask for a password."""
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        return 127


def show_guide(guide: Guide, console: Console, number: int, total: int) -> None:
    body = f"[bold]What it means:[/] {guide.meaning}\n\n[bold]Why it matters:[/] {guide.matters}"
    title = f"[bold]Issue {number}/{total}: {guide.title}[/]"
    console.print(Panel(body, title=title, border_style="red", padding=(1, 2)))


def show_step(step: Step, console: Console, number: int, total: int) -> None:
    kind = "[yellow]\\[change][/]" if step.changes else "[cyan]\\[inspect][/]"
    root = " [red](needs your password)[/]" if step.needs_root else ""
    console.print(f"\n[bold]Step {number}/{total}[/] {kind}{root}")
    console.print(f"  [bold green]$ {shlex.join(step.cmd)}[/]")
    console.print(f"  [bold]What:[/] {step.what}")
    console.print(f"  [bold]Why:[/]  {step.why}")


def show_manual(guide: Guide, console: Console) -> None:
    if guide.manual:
        console.print("\n[bold]Good to know (do these yourself if needed):[/]")
        for tip in guide.manual:
            console.print(f"  • {tip}")
    if guide.docs:
        console.print(f"  docs: [link={guide.docs}]{guide.docs}[/link]")


def problems(results: list[Result]) -> list[tuple[Result, Guide]]:
    return [(r, g) for r in results if (g := guide_for(r)) is not None]


def explain(results: list[Result], console: Console) -> None:
    """Print every guide without running anything."""
    found = problems(results)
    if not found:
        console.print("[green]Nothing to fix.[/]")
        return
    for i, (_, guide) in enumerate(found, 1):
        show_guide(guide, console, i, len(found))
        for j, step in enumerate(guide.steps, 1):
            show_step(step, console, j, len(guide.steps))
        show_manual(guide, console)
        console.print()


def fix(
    results: list[Result],
    console: Console,
    ask: Ask = default_ask,
    runner: Runner = default_runner,
) -> None:
    """Interactive mentor: each command runs only after the user answers 'r'."""
    found = problems(results)
    if not found:
        console.print("[green]Nothing to fix.[/]")
        return
    console.print(
        "[bold]Guided fix mode.[/] For every step: [bold]r[/]un it, [bold]s[/]kip it, "
        "or [bold]q[/]uit. inspect steps only read, change steps modify your system.\n"
    )
    for i, (result, guide) in enumerate(found, 1):
        show_guide(guide, console, i, len(found))
        for j, step in enumerate(guide.steps, 1):
            show_step(step, console, j, len(guide.steps))
            answer = ask("  Run this command?").strip().lower()
            if answer == "q":
                console.print("[dim]Stopped. Run sysreport --fix again any time.[/]")
                return
            if answer != "r":
                console.print("  [dim]skipped[/]")
                continue
            console.rule(style="dim")
            code = runner(step.cmd)
            console.rule(style="dim")
            if code == 0:
                console.print("  [green]✔ done[/]")
            else:
                console.print(
                    f"  [red]✖ exited with code {code}[/], see the output above"
                )
        show_manual(guide, console)
        recheck = CHECKS_BY_KEY.get(result.key)
        if recheck is not None:
            after = recheck()
            color = {Status.OK: "green", Status.WARN: "yellow", Status.FAIL: "red"}.get(
                after.status, "dim"
            )
            console.print(
                f"\n[bold]Re-check:[/] {after.name} → [{color}]{after.status.value}: "
                f"{after.detail}[/]\n"
            )
    console.print(
        "[bold green]All issues reviewed.[/] Run sysreport to see the full picture."
    )
