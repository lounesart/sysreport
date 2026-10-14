"""Tests fake each command's output, so they pass on any machine (and in CI)."""

import subprocess
from datetime import datetime, timedelta

import pytest

import sysreport
from sysreport import checks
from sysreport.checks import Result, Status


def fake_run(outputs: dict[str, tuple[int, str] | None]):
    """Build a replacement for checks.run: key = command name, value = (exit code, stdout)."""

    def _run(cmd, timeout=60):
        out = outputs.get(cmd[0], outputs.get(" ".join(cmd)))
        if out is None:
            return None
        code, stdout = out
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")

    return _run


@pytest.fixture
def use(monkeypatch):
    def _use(outputs):
        monkeypatch.setattr(checks, "run", fake_run(outputs))

    return _use


def test_updates_none(use):
    use({"checkupdates": (2, "")})
    assert checks.check_updates().status is Status.OK


def test_updates_pending(use):
    use({"checkupdates": (0, "a 1 -> 2\nb 3 -> 4\n")})
    result = checks.check_updates()
    assert result.status is Status.WARN
    assert "2 update" in result.detail


def test_updates_tool_missing(use):
    use({})
    assert checks.check_updates().status is Status.SKIP


def test_cves_fixable_is_failure(use):
    use({"arch-audit": (0, "openssl\nlibxml2\n")})
    result = checks.check_cves()
    assert result.status is Status.FAIL
    assert "2 package" in result.detail


def test_failed_units(use):
    use({"systemctl": (0, "foo.service loaded failed failed Foo\n")})
    result = checks.check_failed_units()
    assert result.status is Status.FAIL
    assert result.detail == "foo.service"


def test_firewall_enabled(use):
    use({"systemctl": (0, "enabled\n")})
    assert checks.check_firewall().status is Status.OK


def test_firewall_missing(use):
    use({"systemctl": (1, "disabled\n")})
    assert checks.check_firewall().status is Status.FAIL


def test_snapshots_age(use):
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    use({"snapper": (0, f"number,date\n0,\n1,{old}\n")})
    result = checks.check_snapshots()
    assert result.status is Status.WARN
    assert "1 snapshot" in result.detail


def test_apparmor(tmp_path):
    param = tmp_path / "enabled"
    param.write_text("Y\n")
    assert checks.check_apparmor(param).status is Status.OK
    assert checks.check_apparmor(tmp_path / "missing").status is Status.WARN


def test_time_sync(use):
    use({"timedatectl": (0, "no\n")})
    assert checks.check_time_sync().status is Status.WARN


@pytest.mark.parametrize(
    ("statuses", "code"),
    [
        ([Status.OK, Status.SKIP], 0),
        ([Status.OK, Status.WARN], 1),
        ([Status.WARN, Status.FAIL], 2),
    ],
)
def test_exit_code(statuses, code):
    results = [Result("x", s, "") for s in statuses]
    assert sysreport.exit_code(results) == code


def test_broken_check_is_skipped(monkeypatch):
    def boom():
        raise RuntimeError("kaput")

    monkeypatch.setattr(sysreport, "ALL_CHECKS", [boom])
    [result] = sysreport.collect()
    assert result.status is Status.SKIP
    assert "kaput" in result.detail
