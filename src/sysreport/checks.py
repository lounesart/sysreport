"""Read-only system health checks. Each check returns a Result and never needs root."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class Result:
    name: str
    status: Status
    detail: str
    key: str = ""  # stable id, used to look up the fix guide
    items: tuple[str, ...] = ()  # specifics for the guide (e.g. failed unit names)

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "status": self.status.value, "items": list(self.items)}


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str] | None:
    """Run a command, or return None if it isn't installed."""
    if shutil.which(cmd[0]) is None:
        return None
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def check_updates() -> Result:
    name, key = "Pending updates", "updates"
    proc = run(["checkupdates"], timeout=120)
    if proc is None:
        return Result(name, Status.SKIP, "checkupdates not found (pacman-contrib)", key)
    if proc.returncode == 2:  # checkupdates: 2 = no updates
        return Result(name, Status.OK, "system is up to date", key)
    if proc.returncode != 0:
        return Result(name, Status.SKIP, "could not check (offline?)", key)
    pkgs = tuple(line.split()[0] for line in lines(proc.stdout))
    return Result(name, Status.WARN, f"{len(pkgs)} update(s) available", key, pkgs)


def check_cves() -> Result:
    name, key = "Fixable CVEs", "cves"
    proc = run(["arch-audit", "-u"])
    if proc is None:
        return Result(name, Status.SKIP, "arch-audit not installed", key)
    vulnerable = tuple(lines(proc.stdout))
    if not vulnerable:
        return Result(name, Status.OK, "no vulnerabilities fixable by updating", key)
    detail = f"{len(vulnerable)} package(s), update now"
    return Result(name, Status.FAIL, detail, key, vulnerable)


def check_failed_units() -> Result:
    name, key = "Failed services", "failed_units"
    proc = run(["systemctl", "list-units", "--failed", "--no-legend", "--plain"])
    if proc is None:
        return Result(name, Status.SKIP, "systemd not found", key)
    failed = tuple(line.split()[0] for line in lines(proc.stdout))
    if not failed:
        return Result(name, Status.OK, "none", key)
    return Result(name, Status.FAIL, ", ".join(failed), key, failed)


def check_firewall() -> Result:
    name, key = "Firewall", "firewall"
    for service in ("nftables", "ufw", "firewalld"):
        proc = run(["systemctl", "is-enabled", service])
        if proc is not None and proc.stdout.strip() == "enabled":
            return Result(name, Status.OK, f"{service} enabled at boot", key)
    detail = "no firewall service enabled (nftables/ufw/firewalld)"
    return Result(name, Status.FAIL, detail, key)


def check_snapshots(max_age_days: int = 14) -> Result:
    name, key = "Snapshots", "snapshots"
    proc = run(
        ["snapper", "--csvout", "-c", "root", "list", "--columns", "number,date"]
    )
    if proc is None:
        return Result(name, Status.SKIP, "snapper not installed", key)
    if proc.returncode != 0:
        return Result(
            name, Status.SKIP, "no snapper 'root' config or no permission", key
        )
    dates = []
    for row in lines(proc.stdout)[1:]:  # skip CSV header
        number, _, date = row.partition(",")
        if number != "0" and date:
            dates.append(datetime.strptime(date, "%Y-%m-%d %H:%M:%S"))
    if not dates:
        return Result(name, Status.WARN, "no snapshots yet", key)
    age = (datetime.now() - max(dates)).days
    status = Status.OK if age <= max_age_days else Status.WARN
    return Result(
        name, status, f"{len(dates)} snapshot(s), newest {age} day(s) old", key
    )


def check_disk(path: str = "/") -> Result:
    name, key = f"Disk space {path}", "disk"
    usage = shutil.disk_usage(path)
    pct = usage.used / usage.total * 100
    free_gb = usage.free / 1024**3
    detail = f"{pct:.0f}% used, {free_gb:.0f} GB free"
    if pct >= 90:
        return Result(name, Status.FAIL, detail, key)
    if pct >= 80:
        return Result(name, Status.WARN, detail, key)
    return Result(name, Status.OK, detail, key)


def check_apparmor(
    param: Path = Path("/sys/module/apparmor/parameters/enabled"),
) -> Result:
    name, key = "AppArmor", "apparmor"
    try:
        enabled = param.read_text().strip() == "Y"
    except OSError:
        return Result(name, Status.WARN, "not available in this kernel", key)
    if enabled:
        return Result(name, Status.OK, "enabled", key)
    return Result(name, Status.WARN, "module present but disabled", key)


def check_usbguard() -> Result:
    name, key = "USBGuard", "usbguard"
    proc = run(["systemctl", "is-active", "usbguard"])
    if proc is None or shutil.which("usbguard") is None:
        return Result(name, Status.SKIP, "not installed", key)
    if proc.stdout.strip() != "active":
        return Result(
            name, Status.WARN, "installed but not running", key, ("inactive",)
        )
    blocked = run(["usbguard", "list-devices", "--blocked"])
    found = tuple(lines(blocked.stdout)) if blocked and blocked.returncode == 0 else ()
    if found:
        detail = f"active, {len(found)} blocked device(s) waiting for review"
        return Result(name, Status.WARN, detail, key, found)
    return Result(name, Status.OK, "active, no blocked devices", key)


def check_time_sync() -> Result:
    name, key = "Clock sync", "time_sync"
    proc = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if proc is None:
        return Result(name, Status.SKIP, "timedatectl not found", key)
    if proc.stdout.strip() == "yes":
        return Result(name, Status.OK, "synchronized", key)
    return Result(name, Status.WARN, "not synchronized", key)


def check_journal_errors() -> Result:
    name, key = "Errors this boot", "journal_errors"
    proc = run(["journalctl", "-b", "-p", "3", "-q", "--no-pager"])
    if proc is None:
        return Result(name, Status.SKIP, "journalctl not found", key)
    count = len(lines(proc.stdout))
    if count == 0:
        return Result(name, Status.OK, "none", key)
    return Result(name, Status.WARN, f"{count} error message(s)", key)


ALL_CHECKS: list[Callable[[], Result]] = [
    check_updates,
    check_cves,
    check_failed_units,
    check_firewall,
    check_snapshots,
    check_disk,
    check_apparmor,
    check_usbguard,
    check_time_sync,
    check_journal_errors,
]

CHECKS_BY_KEY: dict[str, Callable[[], Result]] = {
    "updates": check_updates,
    "cves": check_cves,
    "failed_units": check_failed_units,
    "firewall": check_firewall,
    "snapshots": check_snapshots,
    "disk": check_disk,
    "apparmor": check_apparmor,
    "usbguard": check_usbguard,
    "time_sync": check_time_sync,
    "journal_errors": check_journal_errors,
}
