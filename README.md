# hdd_temp

Minimal terminal revival of `hddtemp` for modern Linux hosts.

## What this provides

- Direct mode: print drive temperatures in terminal output.
- Daemon mode: TCP server on port `7634` with legacy-style field framing.
- `TYPE:/dev/...` drive prefixes (`SATA`, `PATA`, `ATA`, `SCSI`, `NVME`) for `smartctl -d` hints.
- Poll caching in daemon mode (default 60 seconds), similar to historical `hddtemp`.

## Requirements

- Linux
- Python 3.7 or newer
- `smartctl` with JSON output (`-j`) from `smartmontools`

## Setup Walkthrough (Copy/Paste)

### 1) Download the project (pick one block)

HTTPS:

```bash
git clone https://github.com/warner-family-dev/hdd_temp.git
cd hdd_temp
```

SSH:

```bash
git clone git@github.com:warner-family-dev/hdd_temp.git
cd hdd_temp
```

ZIP (no git history):

```bash
curl -L -o hdd_temp-main.zip https://github.com/warner-family-dev/hdd_temp/archive/refs/heads/main.zip
unzip hdd_temp-main.zip
cd hdd_temp-main
```

### 2) Install dependencies

Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3 smartmontools
```

### 3) Run locally from repo root

```bash
./hddtemp /dev/sda
```

### 4) Install global command (optional)

Run these commands from the repo root:

```bash
sudo install -m 0755 ./hddtemp /usr/local/bin/hddtemp
sudo install -m 0755 ./hddtemp.py /usr/local/bin/hddtemp.py
```

Then use it globally:

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

## Optional systemd service

After installing the global command, create the service's defaults file with
`sudoedit /etc/default/hddtemp-compat`. List your actual drive paths in the
order clients should receive them. For example:

```ini
HDDTEMP_DRIVES="/dev/sda NVME:/dev/nvme0n1"
```

The service runs in the foreground on IPv4 loopback port 7634. Stop any
existing listener on that port before enabling it. Run from the repository:

```bash
sudo install -m 0644 systemd/hddtemp-compat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hddtemp-compat.service
systemctl status hddtemp-compat.service
nc 127.0.0.1 7634
```

Restart the service after changing the drive list. Use your existing manual
`--listen` configuration for remote clients. Reading some devices requires
elevated privileges. The default probe passes `-n standby` to smartctl.
Power-mode detection depends on the drive and controller. Use `-w` only if
you want to allow waking a disk.

## Reading compatibility

Direct and daemon modes prefer smartctl's current Celsius measurement.
The ATA fallback accepts recognized temperature attributes with a Celsius
raw value or a decoded current/min/max string. Vendor health scores, packed
integers without a decoded temperature, and ambiguous fields can now yield
`NOS`. In particular, an SSD life percentage is never a temperature.
A confirmed sleeping drive yields `SLP`. An unsuccessful probe yields
`ERR` when it cannot produce a reading or a more specific status.
SMART health warnings can accompany a valid temperature.

Direct mode writes temperatures to stdout and diagnostics to stderr.
A hard probe error gives exit status 1. The legacy `-n -q` mode prints
`0` for an unreadable drive and treats it as success, so consumers needing
to distinguish an error from zero degrees should use another output mode.

## Tests and release checks

```bash
python3 -B -m unittest discover -s tests -v
```

The suite runs without root or disk access. It invokes the installed-style
launcher with a fake smartctl and checks the TCP response, stop signals,
and reuse of the same port. CI includes Python 3.7 and the current Python 3
release, plus distribution environments:

- Debian 12 and 13
- Ubuntu 22.04 LTS and 24.04 LTS

Before replacing a working installation, keep its executable and Python file
together. During normal polling, compare the old and new CLI output for
representative drives. Check known-good temperatures against smartctl's
explicit current reading and account for normal drift between samples.
Use a drive already in standby to verify the default probe preserves its
power state using the controller's normal monitoring. Test your existing
TCP client against a foreground candidate on an unused loopback port before
switching port 7634. Record the model, controller, smartctl version, and
any reading corrected to an unavailable status. Restore the previous pair
of files and restart the original service if the comparison fails.
