"""Fix guides: for each problem, an explanation and the commands to fix it.

Commands are argument lists (never shell strings), so values taken from check
results (like a service name) can't be interpreted as shell code.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sysreport.checks import Result, Status


@dataclass(frozen=True)
class Step:
    cmd: list[str]
    what: str  # what the command does
    why: str  # why we run it at this point
    changes: bool = False  # False = read-only inspection, True = modifies the system

    @property
    def needs_root(self) -> bool:
        return self.cmd[0] == "sudo"


@dataclass(frozen=True)
class Guide:
    title: str
    meaning: str  # what the finding means
    matters: str  # why it matters
    steps: list[Step] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)  # advice we never automate
    docs: str = ""


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def _updates(r: Result) -> Guide:
    return Guide(
        title="Pending updates",
        meaning=f"{len(r.items)} installed package(s) have newer versions available.",
        matters="Updates carry security fixes. On Arch (a rolling release) always upgrade "
        "the whole system at once. Partial upgrades aren't supported and can break things.",
        steps=[
            Step(
                ["checkupdates"],
                "Lists the packages that would be upgraded, without touching the system.",
                "See what's coming. Kernel or systemd updates need a reboot afterwards.",
            ),
            Step(
                ["sudo", "pacman", "-Syu"],
                "Syncs package databases (-y) and upgrades every installed package (-u).",
                "This is the only supported way to update Arch. If snap-pac is installed, "
                "snapper takes a snapshot before and after automatically.",
                changes=True,
            ),
        ],
        manual=[
            "Before big updates, check https://archlinux.org/news for any manual steps.",
            "After a kernel update, reboot: the running kernel (uname -r) stays old until then.",
            "Watch for '.pacnew' messages; merge them later with: pacdiff",
        ],
        docs="https://wiki.archlinux.org/title/System_maintenance",
    )


def _cves(r: Result) -> Guide:
    return Guide(
        title="Fixable vulnerabilities",
        meaning=f"{len(r.items)} installed package(s) have known security holes (CVEs) "
        "that are ALREADY fixed in newer versions in the repositories.",
        matters="These are the easiest security wins: the fix exists, you just haven't "
        "installed it yet. Attackers scan for exactly these known holes.",
        steps=[
            Step(
                ["arch-audit", "-u"],
                "Shows each vulnerable package, the type of issue and the fixed version.",
                "Understand the risk before acting (e.g. remote code execution vs. local DoS).",
            ),
            Step(
                ["sudo", "pacman", "-Syu"],
                "Full system upgrade, which installs the fixed versions.",
                "Updating is the fix. Run sysreport again afterwards to confirm.",
                changes=True,
            ),
        ],
        manual=[
            "If a vulnerable program is running (browser, server), restart it after updating.",
        ],
        docs="https://security.archlinux.org",
    )


def _failed_units(r: Result) -> Guide:
    steps: list[Step] = []
    for unit in r.items:
        steps += [
            Step(
                ["systemctl", "status", "--no-pager", unit],
                f"Shows the state of {unit}, its exit code and its last log lines.",
                "The status usually tells you WHY it failed (missing file, bad config...).",
            ),
            Step(
                ["journalctl", "-b", "-u", unit, "--no-pager", "-n", "30"],
                f"Shows the last 30 log lines of {unit} from this boot.",
                "More context than status. Look for the first error, not the last one.",
            ),
            Step(
                ["sudo", "systemctl", "restart", unit],
                f"Stops and starts {unit} again.",
                "Fixes transient failures (e.g. network not ready at boot). If it fails "
                "again, fix the cause found in the logs first.",
                changes=True,
            ),
        ]
    return Guide(
        title="Failed services",
        meaning="These systemd services tried to start and crashed or exited with an error: "
        + ", ".join(r.items),
        matters="A failed service may mean a missing feature (no network, no sound, no "
        "backups) or a broken config after an update.",
        steps=steps,
        manual=[
            "Don't need the service? Disable it: sudo systemctl disable --now <unit>",
            "Clear the 'failed' mark after fixing: sudo systemctl reset-failed <unit>",
            "Search the exact error message online, together with the service name.",
        ],
        docs="https://wiki.archlinux.org/title/Systemd#Using_units",
    )


def _firewall(_: Result) -> Guide:
    steps = [
        Step(
            ["ss", "-tuln"],
            "Lists every port this machine listens on (t=TCP, u=UDP, l=listening, n=numeric).",
            "Anything bound to 0.0.0.0 or [::] is reachable from the network. That's "
            "what a firewall would protect.",
        ),
    ]
    if has("pacman"):
        steps.append(
            Step(
                ["sudo", "pacman", "-S", "--needed", "nftables"],
                "Installs nftables, the modern Linux firewall (skipped if present).",
                "Arch ships a sensible default ruleset in /etc/nftables.conf.",
                changes=True,
            )
        )
    if Path("/etc/nftables.conf").exists() or has("pacman"):
        steps += [
            Step(
                ["cat", "/etc/nftables.conf"],
                "Prints the firewall rules that will be loaded.",
                "Always read rules before enabling them. Arch's default ALLOWS SSH (port "
                "22), so remove that line if you don't run an SSH server.",
            ),
            Step(
                ["sudo", "systemctl", "enable", "--now", "nftables"],
                "Loads the rules now (--now) and at every boot (enable).",
                "Default-deny incoming blocks unsolicited connections while everything "
                "you start (browsing, updates) keeps working.",
                changes=True,
            ),
        ]
    return Guide(
        title="No firewall",
        meaning="No firewall service (nftables, ufw or firewalld) is enabled at boot.",
        matters="Without a firewall, any service that listens on the network is reachable "
        "by every device on the same network, including public Wi-Fi.",
        steps=steps,
        manual=["Check what's blocked later: journalctl -k | grep -i drop"],
        docs="https://wiki.archlinux.org/title/Nftables",
    )


def _snapshots(r: Result) -> Guide:
    return Guide(
        title="Snapshots",
        meaning=f"Snapshot status: {r.detail}.",
        matters="Btrfs snapshots let you roll back a broken update or a bad config change "
        "in minutes. An old newest snapshot means your safety net is outdated.",
        steps=[
            Step(
                ["snapper", "-c", "root", "list"],
                "Lists existing snapshots with their number, date and description.",
                "See what restore points you already have.",
            ),
            Step(
                ["sudo", "snapper", "-c", "root", "create", "-d", "sysreport manual"],
                "Creates a new snapshot of the root filesystem right now.",
                "Takes a second and almost no space (copy-on-write); gives you a fresh "
                "restore point.",
                changes=True,
            ),
        ],
        manual=[
            "Snapshots live on the same disk: also keep an off-disk backup of your files.",
            "Install snap-pac to snapshot automatically before every pacman update.",
        ],
        docs="https://wiki.archlinux.org/title/Snapper",
    )


def _disk(r: Result) -> Guide:
    steps = [
        Step(
            ["du", "-h", "-d", "1", str(Path.home())],
            "Shows how much space each folder in your home directory uses.",
            "Find the big folders first, usually Downloads, caches or VM images.",
        ),
        Step(
            ["journalctl", "--disk-usage"],
            "Shows how much space system logs take.",
            "Logs can grow to gigabytes on systems that run for months.",
        ),
    ]
    if has("paccache"):
        steps.append(
            Step(
                ["sudo", "paccache", "-rk1"],
                "Removes cached package files, keeping only the newest version of each.",
                "pacman keeps every downloaded version; old ones are rarely needed.",
                changes=True,
            )
        )
    steps.append(
        Step(
            ["sudo", "journalctl", "--vacuum-time=2weeks"],
            "Deletes system logs older than two weeks.",
            "Frees log space while keeping recent history for troubleshooting.",
            changes=True,
        )
    )
    return Guide(
        title="Low disk space",
        meaning=f"The root filesystem is filling up: {r.detail}.",
        matters="A full disk makes updates fail halfway, apps crash and logs stop. "
        "Btrfs in particular misbehaves when nearly full.",
        steps=steps,
        manual=[
            (
                "On Btrfs, old snapshots hold space: snapper -c root list, then "
                "sudo snapper -c root delete <number>"
            ),
            "Accurate Btrfs usage: sudo btrfs filesystem usage /",
        ],
        docs="https://wiki.archlinux.org/title/Pacman#Cleaning_the_package_cache",
    )


def _apparmor(r: Result) -> Guide:
    return Guide(
        title="AppArmor",
        meaning=f"AppArmor is {r.detail}.",
        matters="AppArmor confines programs to the files and actions their profile allows, "
        "limiting the damage a compromised app can do.",
        steps=[
            Step(
                ["cat", "/sys/kernel/security/lsm"],
                "Lists the Linux security modules active in the running kernel.",
                "If 'apparmor' is missing here, the kernel wasn't told to load it at boot.",
            ),
        ],
        manual=[
            "Enabling needs a kernel boot parameter, which sysreport won't change for you:",
            (
                "add lsm=landlock,lockdown,yama,integrity,apparmor,bpf to "
                "GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub,"
            ),
            (
                "then: sudo grub-mkconfig -o /boot/grub/grub.cfg, "
                "sudo systemctl enable apparmor, reboot."
            ),
        ],
        docs="https://wiki.archlinux.org/title/AppArmor",
    )


def _usbguard(r: Result) -> Guide:
    if r.items == ("inactive",):
        return Guide(
            title="USBGuard not running",
            meaning="USBGuard is installed but its daemon isn't running, so USB devices "
            "are not being checked.",
            matters="USBGuard blocks 'BadUSB' devices that pretend to be keyboards and "
            "type commands. Starting it WITHOUT a policy can block your own keyboard.",
            steps=[
                Step(
                    ["systemctl", "status", "--no-pager", "usbguard"],
                    "Shows whether the daemon failed or was never enabled.",
                    "A failed start often means a bad /etc/usbguard/rules.conf.",
                ),
                Step(
                    ["usbguard", "generate-policy"],
                    "Prints allow-rules for every USB device connected right now.",
                    "Check the list. It should only contain devices you recognise.",
                ),
            ],
            manual=[
                (
                    "Plug in your usual devices, then save the policy (as root) to "
                    "/etc/usbguard/rules.conf with mode 0600."
                ),
                "Only then: sudo systemctl enable --now usbguard",
                "On a laptop, the built-in keyboard usually isn't USB, so it keeps working.",
            ],
            docs="https://wiki.archlinux.org/title/USBGuard",
        )
    return Guide(
        title="Blocked USB devices",
        meaning=f"{len(r.items)} USB device(s) were plugged in and blocked because no rule "
        "allows them.",
        matters="That's USBGuard working. Decide per device whether it's legitimate.",
        steps=[
            Step(
                ["usbguard", "list-devices", "--blocked"],
                "Lists blocked devices with their ID, name and interface classes.",
                "Compare what the device claims with what it is: a USB stick should "
                "show only class 08 (storage). A stick showing 03 (keyboard) is a red flag.",
            ),
        ],
        manual=[
            "Allow once:          usbguard allow-device <id>",
            "Allow permanently:   usbguard allow-device -p <id>",
            "sysreport won't allow devices for you. You have to decide that.",
        ],
        docs="https://usbguard.github.io/documentation/rule-language.html",
    )


def _time_sync(_: Result) -> Guide:
    return Guide(
        title="Clock not synchronized",
        meaning="The system clock is not being synchronized with internet time servers.",
        matters="Wrong time breaks HTTPS certificate checks, 2FA codes and makes logs "
        "useless for investigating problems.",
        steps=[
            Step(
                ["timedatectl", "status"],
                "Shows local time, time zone and whether NTP sync is active.",
                "Confirm the problem and check the time zone is right.",
            ),
            Step(
                ["sudo", "timedatectl", "set-ntp", "true"],
                "Enables systemd-timesyncd, which keeps the clock in sync automatically.",
                "Built in, lightweight, no extra packages needed.",
                changes=True,
            ),
        ],
        docs="https://wiki.archlinux.org/title/Systemd-timesyncd",
    )


def _journal_errors(r: Result) -> Guide:
    return Guide(
        title="Errors this boot",
        meaning=f"The system log recorded {r.detail} since boot.",
        matters="Most boot-time errors are harmless noise (firmware quirks, optional "
        "hardware), but a repeating error can point to a real problem.",
        steps=[
            Step(
                ["journalctl", "-b", "-p", "3", "--no-pager", "-n", "40"],
                "Shows the last 40 messages of priority 'error' or worse from this boot.",
                "Look for errors that repeat or mention something you use (Wi-Fi, sound, "
                "disk). One-off firmware/ACPI lines are usually safe to ignore.",
            ),
            Step(
                ["journalctl", "-b", "-1", "-p", "3", "--no-pager", "-n", "20"],
                "Shows errors from the PREVIOUS boot.",
                "An error in every boot is a pattern worth fixing; a one-time one usually "
                "isn't.",
            ),
        ],
        manual=[
            "Search the exact error text online with your hardware/distro name.",
            "Errors from a failed service also show up under 'Failed services'.",
        ],
        docs="https://wiki.archlinux.org/title/Systemd/Journal",
    )


BUILDERS = {
    "updates": _updates,
    "cves": _cves,
    "failed_units": _failed_units,
    "firewall": _firewall,
    "snapshots": _snapshots,
    "disk": _disk,
    "apparmor": _apparmor,
    "usbguard": _usbguard,
    "time_sync": _time_sync,
    "journal_errors": _journal_errors,
}


def guide_for(result: Result) -> Guide | None:
    """Return a guide for a problem result, or None when there's nothing to fix."""
    if result.status in (Status.OK, Status.SKIP):
        return None
    builder = BUILDERS.get(result.key)
    return builder(result) if builder else None
