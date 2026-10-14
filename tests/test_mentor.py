"""Mentor tests: answers are simulated and the command runner is a recorder — nothing runs."""

import io

import pytest
from rich.console import Console

from sysreport import mentor
from sysreport.checks import CHECKS_BY_KEY, Result, Status
from sysreport.guides import BUILDERS, guide_for


def quiet_console() -> Console:
    return Console(file=io.StringIO(), width=120)


def problem(key: str, items: tuple[str, ...] = ()) -> Result:
    return Result(key, Status.WARN, "detail", key, items)


@pytest.fixture(autouse=True)
def no_rechecks(monkeypatch):
    """Re-checks would run real commands; replace them with a fixed ok result."""
    fake = {k: (lambda k=k: Result(k, Status.OK, "fixed", k)) for k in CHECKS_BY_KEY}
    monkeypatch.setattr(mentor, "CHECKS_BY_KEY", fake)


def recorder():
    calls: list[list[str]] = []

    def runner(cmd):
        calls.append(cmd)
        return 0

    return calls, runner


def answers(*seq):
    it = iter(seq)
    return lambda _q: next(it, "q")


def test_every_check_has_a_guide():
    assert set(BUILDERS) == set(CHECKS_BY_KEY)
    for key in CHECKS_BY_KEY:
        guide = guide_for(problem(key, ("example.service",)))
        assert guide is not None, key
        assert guide.meaning and guide.matters, key
        for step in guide.steps:
            assert step.cmd and step.what and step.why, key


def test_ok_and_skip_have_no_guide():
    assert guide_for(Result("x", Status.OK, "", "updates")) is None
    assert guide_for(Result("x", Status.SKIP, "", "updates")) is None


def test_skip_runs_nothing():
    calls, runner = recorder()
    mentor.fix([problem("time_sync")], quiet_console(), answers("s", "s"), runner)
    assert calls == []


def test_run_executes_exact_command():
    calls, runner = recorder()
    mentor.fix([problem("time_sync")], quiet_console(), answers("s", "r"), runner)
    assert calls == [["sudo", "timedatectl", "set-ntp", "true"]]


def test_quit_stops_everything():
    calls, runner = recorder()
    results = [problem("time_sync"), problem("updates", ("a",))]
    mentor.fix(results, quiet_console(), answers("q"), runner)
    assert calls == []


def test_explain_never_runs(monkeypatch):
    monkeypatch.setattr(mentor, "default_runner", lambda cmd: pytest.fail("ran!"))
    mentor.explain([problem("disk"), problem("firewall")], quiet_console())


def test_unit_name_is_one_argument_not_shell():
    evil = "x.service; rm -rf ~"
    guide = guide_for(problem("failed_units", (evil,)))
    assert ["systemctl", "status", "--no-pager", evil] == guide.steps[0].cmd


def test_usbguard_never_auto_allows():
    guide = guide_for(problem("usbguard", ("12: block id 1234:5678",)))
    assert all("allow-device" not in step.cmd for step in guide.steps)
