# sysreport

Quick health check for a Linux workstation. It runs a handful of read-only checks
(updates, CVEs, firewall, snapshots, disk space...) and prints them as a table.
If something's off, it can walk you through fixing it.

I wrote it for my own Arch setup, but most checks work on any systemd distro.

```
$ sysreport
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check            ┃ Status ┃ Details                                ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Pending updates  │ ▲ warn │ 4 update(s) available                  │
│ Fixable CVEs     │ ✔ ok   │ no vulnerabilities fixable by updating │
│ Failed services  │ ✔ ok   │ none                                   │
│ Firewall         │ ✔ ok   │ nftables enabled at boot               │
│ Snapshots        │ ✔ ok   │ 20 snapshot(s), newest 0 day(s) old    │
│ Disk space /     │ ✔ ok   │ 15% used, 106 GB free                  │
│ AppArmor         │ ✔ ok   │ enabled                                │
│ USBGuard         │ ✔ ok   │ active, no blocked devices             │
│ Clock sync       │ ✔ ok   │ synchronized                           │
│ Errors this boot │ ▲ warn │ 8 error message(s)                     │
└──────────────────┴────────┴────────────────────────────────────────┘
8 ok · 2 warn · 0 fail · 0 skipped
```

## Install

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv tool install git+https://github.com/lounesart/sysreport
```

## Usage

```sh
sysreport            # the table
sysreport --explain  # what's wrong and how to fix it (doesn't run anything)
sysreport --fix      # go through the fixes one command at a time
sysreport --json     # JSON output for scripts
```

Exit codes: `0` everything ok, `1` warnings, `2` failures. Useful if you run it from a
script or a systemd timer.

### --fix

For each problem it explains what's going on, then shows the commands to fix it, one
at a time, with a short note on what each command does and why. You pick run, skip
or quit for every single command, and skip is the default. After each problem it runs
the check again so you can see if it worked.

```
Step 2/2 [change] (needs your password)
  $ sudo pacman -Syu
  What: Syncs package databases (-y) and upgrades every installed package (-u).
  Why:  This is the only supported way to update Arch.
  Run this command? [r/s/q] (s):
```

Steps are marked `[inspect]` (only reads) or `[change]` (modifies the system).
Some things are deliberately left to you: it won't allow USB devices or edit kernel
boot parameters, it just tells you how.

## Checks

| Check | Uses |
|---|---|
| Pending updates | `checkupdates` (pacman-contrib) |
| Fixable CVEs | `arch-audit -u` |
| Failed services | `systemctl list-units --failed` |
| Firewall | nftables, ufw or firewalld enabled |
| Snapshots | `snapper`, root config |
| Disk space | `/`, warns at 80%, fails at 90% |
| AppArmor | kernel module status |
| USBGuard | daemon status, blocked devices |
| Clock sync | `timedatectl` |
| Errors this boot | `journalctl -b -p 3` |

Everything runs as your user, no root needed. If a tool isn't installed, that check
is skipped.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
