#!/usr/bin/env python3
"""Modern, minimal hddtemp-compatible terminal utility."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "v0.0.1"
DEFAULT_PORT = 7634
DEFAULT_SEPARATOR = "|"
DEFAULT_MIN_INTERVAL = 60

TYPE_TO_SMARTCTL = {
    "SATA": "sat",
    "PATA": "ata",
    "ATA": "ata",
    "SCSI": "scsi",
    "NVME": "nvme",
}


@dataclass
class DeviceSpec:
    raw: str
    drive: str
    smartctl_type: Optional[str]


@dataclass
class DiskReading:
    drive: str
    model: str
    status: str  # KNOWN | NOS | UNK | NA | SLP | ERR
    temperature_c: Optional[int] = None
    detail: str = ""


def parse_device_spec(raw: str) -> DeviceSpec:
    if ":" not in raw:
        return DeviceSpec(raw=raw, drive=raw, smartctl_type=None)

    prefix, drive = raw.split(":", 1)
    smartctl_type = TYPE_TO_SMARTCTL.get(prefix.upper())
    if smartctl_type and drive:
        return DeviceSpec(raw=raw, drive=drive, smartctl_type=smartctl_type)
    return DeviceSpec(raw=raw, drive=raw, smartctl_type=None)


def parse_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            return int(match.group(0))
    return None


def normalize_temp_c(value: Any) -> Optional[int]:
    parsed = parse_int(value)
    if parsed is None:
        return None
    # Some NVMe reports can be in Kelvin.
    if parsed > 200:
        parsed = parsed - 273
    if parsed < -80 or parsed > 200:
        return None
    return parsed


def first_non_empty_string(candidates: Sequence[Any]) -> Optional[str]:
    for candidate in candidates:
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return None


def extract_model(data: Dict[str, Any], drive: str) -> str:
    device_info = data.get("device", {})
    if not isinstance(device_info, dict):
        device_info = {}

    model = first_non_empty_string(
        [
            data.get("model_name"),
            data.get("nvme_model_name"),
            data.get("scsi_model_name"),
            data.get("product"),
            device_info.get("model_name"),
            device_info.get("name"),
            drive,
        ]
    )
    return model or drive


def extract_temperature_c(data: Dict[str, Any]) -> Optional[int]:
    temp = data.get("temperature")
    if isinstance(temp, dict):
        parsed = normalize_temp_c(temp.get("current"))
        if parsed is not None:
            return parsed

    scsi_temp = data.get("scsi_temperature")
    if isinstance(scsi_temp, dict):
        parsed = normalize_temp_c(scsi_temp.get("current"))
        if parsed is not None:
            return parsed

    nvme_health = data.get("nvme_smart_health_information_log")
    if isinstance(nvme_health, dict):
        parsed = normalize_temp_c(nvme_health.get("temperature"))
        if parsed is not None:
            return parsed

    ata_attrs = data.get("ata_smart_attributes")
    if isinstance(ata_attrs, dict):
        table = ata_attrs.get("table")
        if isinstance(table, list):
            for attr_id in (194, 190, 231):
                for row in table:
                    if not isinstance(row, dict):
                        continue
                    if row.get("id") != attr_id:
                        continue
                    raw = row.get("raw", {})
                    if isinstance(raw, dict):
                        parsed = normalize_temp_c(raw.get("value"))
                        if parsed is not None:
                            return parsed
                    parsed = normalize_temp_c(row.get("value"))
                    if parsed is not None:
                        return parsed

    return None


def gather_messages(data: Dict[str, Any], stderr: str) -> str:
    messages: List[str] = []
    smartctl = data.get("smartctl")
    if isinstance(smartctl, dict):
        smartctl_messages = smartctl.get("messages")
        if isinstance(smartctl_messages, list):
            for message in smartctl_messages:
                if not isinstance(message, dict):
                    continue
                value = message.get("string")
                if isinstance(value, str):
                    messages.append(value)
    if stderr:
        messages.append(stderr)
    return "\n".join(messages)


def infer_status_from_messages(messages: str, has_temp: bool) -> str:
    lowered = messages.lower()
    if "standby" in lowered or "sleep" in lowered:
        return "SLP"
    if "permission denied" in lowered or "unable to open device" in lowered:
        return "ERR"
    if "no such device" in lowered or "cannot open" in lowered:
        return "ERR"
    if "smart support is: unavailable" in lowered:
        return "NA"
    if "unknown usb bridge" in lowered:
        return "NA"
    if has_temp:
        return "KNOWN"
    if "temperature" in lowered and "not" in lowered:
        return "NOS"
    return "NOS"


def run_smartctl(spec: DeviceSpec, wake_up: bool, timeout: int = 10) -> DiskReading:
    cmd: List[str] = ["smartctl", "-a", "-j"]
    if spec.smartctl_type:
        cmd.extend(["-d", spec.smartctl_type])
    if not wake_up:
        cmd.extend(["-n", "standby"])
    cmd.append(spec.drive)

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return DiskReading(
            drive=spec.drive,
            model=spec.drive,
            status="ERR",
            detail="smartctl not found (install smartmontools)",
        )
    except subprocess.TimeoutExpired:
        return DiskReading(
            drive=spec.drive,
            model=spec.drive,
            status="ERR",
            detail="smartctl timed out",
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    parsed: Dict[str, Any] = {}

    try:
        parsed = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        message = stderr.strip() or stdout.strip() or "invalid smartctl output"
        return DiskReading(
            drive=spec.drive,
            model=spec.drive,
            status="ERR",
            detail=message,
        )

    model = extract_model(parsed, spec.drive)
    temperature_c = extract_temperature_c(parsed)
    messages = gather_messages(parsed, stderr)
    status = infer_status_from_messages(messages, has_temp=(temperature_c is not None))

    if temperature_c is not None:
        return DiskReading(
            drive=spec.drive,
            model=model,
            status="KNOWN",
            temperature_c=temperature_c,
            detail=messages.strip(),
        )

    return DiskReading(
        drive=spec.drive,
        model=model,
        status=status,
        detail=messages.strip(),
    )


def convert_temperature(temp_c: int, unit: str) -> int:
    if unit == "F":
        return int(round((temp_c * 9.0 / 5.0) + 32.0))
    return temp_c


def direct_mode_output(
    reading: DiskReading, numeric: bool, quiet: bool, unit: str
) -> Tuple[str, bool, bool]:
    if reading.status == "KNOWN" and reading.temperature_c is not None:
        value = convert_temperature(reading.temperature_c, unit)
        if numeric:
            return f"{value}\n", True, False
        return f"{reading.drive}: {reading.model}: {value}\N{DEGREE SIGN}{unit}\n", True, False

    if numeric and quiet:
        return "0\n", True, False

    if reading.status == "SLP":
        return f"{reading.drive}: {reading.model}: drive is sleeping\n", False, False
    if reading.status in {"NOS", "UNK"}:
        return f"{reading.drive}: {reading.model}: no sensor\n", False, False
    if reading.status == "NA":
        return f"{reading.drive}: {reading.model}: not supported\n", False, False

    detail = reading.detail if reading.detail else "temperature query failed"
    return f"{reading.drive}: {reading.model}: {detail}\n", False, True


def format_daemon_payload(readings: Sequence[DiskReading], separator: str, unit: str) -> str:
    items: List[str] = []
    for reading in readings:
        if reading.status == "KNOWN" and reading.temperature_c is not None:
            value = convert_temperature(reading.temperature_c, unit)
            items.append(
                f"{separator}{reading.drive}{separator}{reading.model}"
                f"{separator}{value}{separator}{unit}{separator}"
            )
            continue

        status_field = {
            "NA": "NA",
            "UNK": "UNK",
            "NOS": "NOS",
            "SLP": "SLP",
            "ERR": "ERR",
        }.get(reading.status, "ERR")
        items.append(
            f"{separator}{reading.drive}{separator}{reading.model}"
            f"{separator}{status_field}{separator}*{separator}"
        )

    return "".join(items)


class ReadingCache:
    def __init__(self, devices: Sequence[DeviceSpec], wake_up: bool, min_interval: int):
        self.devices = list(devices)
        self.wake_up = wake_up
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.last_update = 0.0
        self.readings: List[DiskReading] = []

    def get(self) -> List[DiskReading]:
        with self.lock:
            now = time.monotonic()
            if not self.readings or (now - self.last_update) >= self.min_interval:
                self.readings = [run_smartctl(device, wake_up=self.wake_up) for device in self.devices]
                self.last_update = now
            return list(self.readings)


class HDDTempTCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: "HDDTempServer" = self.server  # type: ignore[assignment]
        payload = format_daemon_payload(
            readings=server.cache.get(),
            separator=server.separator,
            unit=server.unit,
        )
        self.request.sendall(payload.encode("utf-8"))


class HDDTempServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        handler_class: type,
        cache: ReadingCache,
        separator: str,
        unit: str,
    ) -> None:
        self.cache = cache
        self.separator = separator
        self.unit = unit
        super().__init__(server_address, handler_class)


def daemonize() -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    os.chdir("/")
    os.umask(0)

    with open(os.devnull, "r", encoding="utf-8") as devnull_in:
        os.dup2(devnull_in.fileno(), 0)
    with open(os.devnull, "a+", encoding="utf-8") as devnull_out:
        os.dup2(devnull_out.fileno(), 1)
        os.dup2(devnull_out.fileno(), 2)


def run_direct_mode(args: argparse.Namespace, devices: Sequence[DeviceSpec]) -> int:
    exit_code = 0
    for device in devices:
        reading = run_smartctl(device, wake_up=args.wake_up)
        output, to_stdout, hard_error = direct_mode_output(
            reading=reading,
            numeric=args.numeric,
            quiet=args.quiet,
            unit=args.unit,
        )
        stream = sys.stdout if to_stdout else sys.stderr
        stream.write(output)
        if hard_error:
            exit_code = 1
    return exit_code


def choose_socket_family(args: argparse.Namespace, host: str) -> int:
    if args.ipv4:
        return socket.AF_INET
    if args.ipv6:
        return socket.AF_INET6
    if ":" in host:
        return socket.AF_INET6
    return socket.AF_INET


def run_daemon_mode(args: argparse.Namespace, devices: Sequence[DeviceSpec]) -> int:
    host = args.listen if args.listen else ("::" if args.ipv6 else "0.0.0.0")
    family = choose_socket_family(args, host)

    cache = ReadingCache(
        devices=devices,
        wake_up=args.wake_up,
        min_interval=args.min_interval,
    )

    class BoundServer(HDDTempServer):
        address_family = family

    server = BoundServer(
        server_address=(host, args.port),
        handler_class=HDDTempTCPHandler,
        cache=cache,
        separator=args.separator,
        unit=args.unit,
    )

    if not args.foreground:
        daemonize()

    stop_requested = {"value": False}

    def handle_stop(_signum: int, _frame: Any) -> None:
        stop_requested["value"] = True
        server.shutdown()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_stop)

    try:
        server.serve_forever()
    finally:
        server.server_close()

    return 0 if stop_requested["value"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hddtemp",
        description="Minimal hddtemp-compatible utility using smartctl.",
    )
    parser.add_argument("drives", nargs="+", help="Drive paths, optional TYPE: prefix (SATA/PATA/SCSI/NVME).")
    parser.add_argument("-d", "--daemon", action="store_true", help="Run in TCP daemon mode.")
    parser.add_argument("-F", "--foreground", action="store_true", help="Stay in foreground in daemon mode.")
    parser.add_argument("-l", "--listen", default=None, help="Listen address in daemon mode.")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help="TCP port in daemon mode.")
    parser.add_argument(
        "-s",
        "--separator",
        default=DEFAULT_SEPARATOR,
        help="Single-character field separator in daemon mode.",
    )
    parser.add_argument("-n", "--numeric", action="store_true", help="Print only numeric temperature in direct mode.")
    parser.add_argument("-q", "--quiet", action="store_true", help="In numeric mode, print 0 for unreadable drives.")
    parser.add_argument("-u", "--unit", choices=["C", "F"], default="C", help="Output unit.")
    parser.add_argument(
        "--min-interval",
        type=int,
        default=DEFAULT_MIN_INTERVAL,
        help="Minimum seconds between drive polls in daemon mode.",
    )
    parser.add_argument("-w", "--wake-up", action="store_true", help="Allow smartctl to wake sleeping drives.")
    parser.add_argument("-4", "--ipv4", action="store_true", help="Use IPv4 sockets.")
    parser.add_argument("-6", "--ipv6", action="store_true", help="Use IPv6 sockets.")
    parser.add_argument("-v", "--version", action="version", version=f"hddtemp {VERSION}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if len(args.separator) != 1:
        parser.error("separator must be exactly one character")
    if args.port < 1 or args.port > 65535:
        parser.error("port must be between 1 and 65535")
    if args.min_interval < 1:
        parser.error("min-interval must be >= 1")
    if args.ipv4 and args.ipv6:
        parser.error("choose either -4 or -6, not both")
    if args.foreground and not args.daemon:
        parser.error("--foreground requires --daemon")

    devices = [parse_device_spec(raw) for raw in args.drives]

    if args.daemon:
        return run_daemon_mode(args, devices)
    return run_direct_mode(args, devices)


if __name__ == "__main__":
    sys.exit(main())
