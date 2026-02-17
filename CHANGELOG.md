# Changelog

All notable changes to this project are documented in this file.

## v0.0.1 (branch: main) - 2026-02-17

### feat
- Added a new root-level `hddtemp.py` terminal utility to restore core `hddtemp` behavior using `smartctl`.
- Added direct mode temperature reporting and daemon mode TCP responses on port `7634`.
- Added support for `TYPE:/dev/...` device prefixes (`SATA`, `PATA`, `ATA`, `SCSI`, `NVME`) and polling cache interval control.

### docu
- Updated `README.md` with install requirements, usage examples, daemon query examples, and project notes.
- Added explicit installation steps and global command setup instructions for `hddtemp`.

### chore
- Added executable wrapper script `hddtemp` for easier local invocation.
- Added basic unit tests in `tests/test_hddtemp.py` for device parsing, temperature extraction, and daemon payload formatting.
- Added `.gitignore` entries for Python bytecode/cache artifacts.
