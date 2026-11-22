# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- Validate smartctl output and use temperature-specific Celsius fields. Vendor
  health scores and ambiguous raw attributes can now report no sensor.
- Distinguish probe errors, standby, and readable temperatures with SMART warnings.
- Stop the TCP daemon cleanly on SIGTERM/SIGINT and measure the poll interval
  from completion of each refresh.
- Add launcher and protocol compatibility tests, CI, and an optional loopback
  systemd service.

## v0.0.1 (branch: main) - 2026-02-17

### feat
- Added a new root-level `hddtemp.py` terminal utility to restore core `hddtemp` behavior using `smartctl`.
- Added direct mode temperature reporting and daemon mode TCP responses on port `7634`.
- Added support for `TYPE:/dev/...` device prefixes (`SATA`, `PATA`, `ATA`, `SCSI`, `NVME`) and polling cache interval control.

### docu
- Updated `README.md` with install requirements, usage examples, daemon query examples, and project notes.
- Added explicit installation steps and global command setup instructions for `hddtemp`.
- Added repository download instructions (HTTPS/SSH clone and ZIP archive workflow).
- Reworked README setup instructions into copy/paste walkthrough steps and removed machine-specific absolute paths.

### chore
- Added executable wrapper script `hddtemp` for easier local invocation.
- Added basic unit tests in `tests/test_hddtemp.py` for device parsing, temperature extraction, and daemon payload formatting.
- Added `.gitignore` entries for Python bytecode/cache artifacts.
- Disconnected `hdd_temp_legacy/` from root repo tracking by ignoring it in `.gitignore`.
