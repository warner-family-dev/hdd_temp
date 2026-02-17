# hdd_temp

Minimal terminal revival of `hddtemp` for modern Linux hosts.

## What this provides

- Direct mode: print drive temperatures in terminal output.
- Daemon mode: TCP server on port `7634` with legacy-style field framing.
- `TYPE:/dev/...` drive prefixes (`SATA`, `PATA`, `ATA`, `SCSI`, `NVME`) for `smartctl -d` hints.
- Poll caching in daemon mode (default 60 seconds), similar to historical `hddtemp`.

## Requirements

- Linux
- `python3`
- `smartctl` from `smartmontools`

## Installation

Install runtime dependencies:

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y python3 smartmontools
```

Run from repository root:

```bash
cd /home/keatre/dev_projects/hdd_temp
./hddtemp /dev/sda
```

## Global Command Setup

Install `hddtemp` into `/usr/local/bin`:

```bash
sudo install -m 0755 /home/keatre/dev_projects/hdd_temp/hddtemp /usr/local/bin/hddtemp
sudo install -m 0755 /home/keatre/dev_projects/hdd_temp/hddtemp.py /usr/local/bin/hddtemp.py
```

Then call it globally from anywhere:

```bash
hddtemp /dev/sda
```

## Usage

Direct mode:

```bash
./hddtemp /dev/sda /dev/nvme0n1
```

Numeric only:

```bash
./hddtemp -n /dev/sda
```

Force Fahrenheit:

```bash
./hddtemp -u F /dev/sda
```

Daemon mode (foreground):

```bash
./hddtemp -d -F -l 127.0.0.1 -p 7634 /dev/sda /dev/nvme0n1
```

Query daemon:

```bash
nc 127.0.0.1 7634
```

## Notes

- If `smartctl` is missing, the tool reports an error for each queried drive.
- Access to some devices can require elevated permissions.
- Historical source remains under `hdd_temp_legacy/` for reference.
