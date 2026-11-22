import concurrent.futures
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import hddtemp


LAUNCHER = str(Path(__file__).resolve().parents[1] / "hddtemp")
FAKE_SMARTCTL = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['HDDTEMP_FIXTURES'])
with (root / 'calls').open('a') as calls:
    print(json.dumps(sys.argv[1:]), file=calls)
reply = json.loads((root / Path(sys.argv[-1]).name).read_text())
sys.stdout.write(reply['stdout'])
sys.stderr.write(reply['stderr'])
sys.exit(reply['code'])
"""


class ProbeTests(unittest.TestCase):
    def test_temperature_sources(self):
        for payload, expected in [
            ({"scsi_temperature": {"current": 32}}, 32),
            ({"nvme_smart_health_information_log": {"temperature": 45}}, 45),
            ({"temperature": {"current": 300}}, None),
            ({"temperature": {"current": True}}, None),
            ({"temperature": {"current": "sensor 1 failed"}}, None),
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(hddtemp.extract_temperature_c(payload), expected)

    def test_attribute_fallback(self):
        for row, expected in [
            ({"id": 231, "name": "SSD_Life_Left", "value": 99, "raw": {"value": 99}}, None),
            ({"id": 194, "name": "Temperature_Celsius", "value": 99}, None),
            ({"id": 231, "name": "Temperature_Celsius", "raw": {"value": 37}}, 37),
            ({"id": 190, "name": "Airflow_Temperature_Cel",
              "raw": {"string": "32 (Min/Max 10/45)", "value": 1234567}}, 32),
            ({"id": 194, "name": "Temperature_Celsius",
              "raw": {"string": "unknown format", "value": 100}}, None),
        ]:
            with self.subTest(row=row):
                payload = {"ata_smart_attributes": {"table": [row]}}
                self.assertEqual(hddtemp.extract_temperature_c(payload), expected)

    def test_timeout(self):
        with patch("hddtemp.subprocess.run", side_effect=subprocess.TimeoutExpired("smartctl", 10)):
            reading = hddtemp.run_smartctl(hddtemp.parse_device_spec("/dev/example"), False)
        self.assertEqual(reading.status, "ERR")
        self.assertIn("timed out", reading.detail)

    def test_waiting_client_reuses_completed_slow_refresh(self):
        now = [100.]
        started = threading.Event()
        release = threading.Event()
        cache = hddtemp.ReadingCache([hddtemp.parse_device_spec("a")], False, 60)

        def slow_probe(spec, wake_up):
            started.set()
            self.assertTrue(release.wait(5))
            now[0] += 65
            return hddtemp.DiskReading(spec.drive, "Disk", "KNOWN", 30)

        with patch("hddtemp.run_smartctl", side_effect=slow_probe) as probe, \
                patch("hddtemp.time.monotonic", side_effect=lambda: now[0]), \
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get)
            self.assertTrue(started.wait(5))
            second = pool.submit(cache.get)
            release.set()
            self.assertEqual(first.result(5), second.result(5))
            self.assertEqual(probe.call_count, 1)
            now[0] += 60
            cache.get()
            self.assertEqual(probe.call_count, 2)


class CommandTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fake = self.root / "smartctl"
        fake.write_text(FAKE_SMARTCTL)
        fake.chmod(0o755)
        self.env = dict(os.environ, HDDTEMP_FIXTURES=temp.name,
                        PATH=temp.name + os.pathsep + os.environ["PATH"])

    def reply(self, drive, data, code=0, stderr=""):
        stdout = data if isinstance(data, str) else json.dumps(data)
        (self.root / drive).write_text(json.dumps(dict(stdout=stdout, stderr=stderr, code=code)))

    def cli(self, *args):
        result = subprocess.run([LAUNCHER, *args], env=self.env, capture_output=True,
                                text=True, timeout=10)
        return result.returncode, result.stdout, result.stderr

    def test_cli_contract(self):
        self.reply("a", {"model_name": "DiskA", "temperature": {"current": 30}}, 8)
        self.reply("b", {"model_name": "DiskB", "power_mode": "STANDBY"}, 2)
        self.assertEqual(self.cli("SATA:/dev/a", "/dev/b"),
                         (0, "/dev/a: DiskA: 30°C\n", "/dev/b: DiskB: drive is sleeping\n"))
        self.assertEqual(self.cli("-n", "-q", "-u", "F", "/dev/a", "/dev/b"), (0, "86\n0\n", ""))
        self.assertEqual(self.cli("-n", "-w", "/dev/a"), (0, "30\n", ""))
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual(calls[0], ["-a", "-j", "-d", "sat", "-n", "standby", "/dev/a"])
        self.assertEqual(calls[-1], ["-a", "-j", "/dev/a"])

    def test_cli_status_with_partial_results(self):
        self.reply("nvme", {"nvme_smart_health_information_log": {"temperature": 42}}, 4)
        self.reply("scsi", {"scsi_temperature": {"current": 27}}, 8,
                   "SMART support is: Unavailable")
        self.assertEqual(self.cli("-n", "NVME:/dev/nvme", "SCSI:/dev/scsi"), (0, "42\n27\n", ""))
        self.reply("asleep", "", 2, "Device is in SLEEP mode, exit(2)")
        self.assertEqual(self.cli("/dev/asleep"),
                         (0, "", "/dev/asleep: /dev/asleep: drive is sleeping\n"))
        self.reply("usb", "", 2, "Unknown USB bridge")
        self.assertEqual(self.cli("/dev/usb"), (0, "", "/dev/usb: /dev/usb: not supported\n"))
        self.reply("ssd", {"ata_smart_attributes": {"table": [
            {"id": 231, "name": "SSD_Life_Left", "value": 99, "raw": {"value": 99}}
        ]}})
        self.assertEqual(self.cli("/dev/ssd"), (0, "", "/dev/ssd: /dev/ssd: no sensor\n"))

    def test_cli_probe_errors(self):
        for data, code, stderr in [("", 2, "Permission denied"), ("broken", 0, ""),
                                   ([], 0, ""), ({}, 4, ""), ({}, 2, "")]:
            with self.subTest(data=data, code=code):
                self.reply("a", data, code, stderr)
                rc, out, err = self.cli("/dev/a")
                self.assertEqual((rc, out), (1, ""))
                self.assertTrue(err.startswith("/dev/a: "))
                self.assertNotIn("Traceback", err)
                self.assertEqual(self.cli("-n", "-q", "/dev/a"), (0, "0\n", ""))

    def test_daemon_protocol_and_restart(self):
        self.reply("a", {"model_name": "DiskA", "scsi_temperature": {"current": 30}})
        self.reply("b", {"smartctl": {"messages": [{"string": "Device is in STANDBY mode, exit(2)"}]}}, 2)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        args = [LAUNCHER, "-d", "-F", "-l", "127.0.0.1", "-p", str(port),
                "-s", ";", "-u", "F", "/dev/b", "/dev/a"]
        for sig in (signal.SIGTERM, signal.SIGINT):
            with subprocess.Popen(args, env=self.env) as daemon:
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            client = socket.create_connection(("127.0.0.1", port), timeout=3)
                            break
                        except ConnectionRefusedError:
                            if daemon.poll() is not None or time.monotonic() > deadline:
                                raise
                            time.sleep(0.03)
                    with client, client.makefile("rb") as stream:
                        self.assertEqual(stream.read(), b";/dev/b;/dev/b;SLP;*;;/dev/a;DiskA;86;F;")
                    daemon.send_signal(sig)
                    self.assertEqual(daemon.wait(timeout=3), 0)
                finally:
                    if daemon.poll() is None:
                        daemon.kill()
