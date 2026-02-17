import unittest

import hddtemp


class HDDTempTests(unittest.TestCase):
    def test_parse_device_spec_with_type_prefix(self) -> None:
        spec = hddtemp.parse_device_spec("SATA:/dev/sda")
        self.assertEqual(spec.drive, "/dev/sda")
        self.assertEqual(spec.smartctl_type, "sat")

    def test_extract_temperature_from_ata_table(self) -> None:
        sample = {
            "ata_smart_attributes": {
                "table": [
                    {"id": 1, "raw": {"value": 0}},
                    {"id": 194, "raw": {"value": 34}},
                ]
            }
        }
        self.assertEqual(hddtemp.extract_temperature_c(sample), 34)

    def test_format_daemon_payload(self) -> None:
        readings = [
            hddtemp.DiskReading(
                drive="/dev/sda",
                model="DiskA",
                status="KNOWN",
                temperature_c=35,
            ),
            hddtemp.DiskReading(
                drive="/dev/sdb",
                model="DiskB",
                status="SLP",
            ),
        ]
        payload = hddtemp.format_daemon_payload(readings, "|", "C")
        self.assertEqual(payload, "|/dev/sda|DiskA|35|C||/dev/sdb|DiskB|SLP|*|")

    def test_convert_temperature_fahrenheit(self) -> None:
        self.assertEqual(hddtemp.convert_temperature(30, "F"), 86)


if __name__ == "__main__":
    unittest.main()
