from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from models import (
    human_duration, duration_minutes, ensure_aware, format_local, parse_timestamp,
    parse_user_timestamp, to_iso, truncate, utc_now,
)


class TimestampTests(unittest.TestCase):
    def test_to_iso_and_parse_round_trip(self) -> None:
        value = datetime(2026, 5, 1, 12, 30, 15, tzinfo=timezone.utc)
        text = to_iso(value)
        self.assertEqual(text, "2026-05-01T12:30:15Z")
        self.assertEqual(parse_timestamp(text), value)
        self.assertIsNone(to_iso(None))

    def test_naive_values_are_treated_as_utc(self) -> None:
        parsed = parse_timestamp("2026-05-01 12:00:00")
        self.assertEqual(parsed, datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(ensure_aware(datetime(2026, 5, 1, 12, 0)),
                         datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))

    def test_offset_timestamps_are_normalised(self) -> None:
        parsed = parse_timestamp("2026-05-01T14:00:00+02:00")
        self.assertEqual(parsed, datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_parse_user_timestamp_formats(self) -> None:
        for raw in ("2026-05-01", "2026-05-01 09:30", "01/05/2026 09:30",
                    "2026-05-01T09:30:00", date(2026, 5, 1)):
            parsed = parse_user_timestamp(raw)
            self.assertEqual(parsed.tzinfo, timezone.utc)
        with self.assertRaises(ValueError):
            parse_user_timestamp("")
        with self.assertRaises(ValueError):
            parse_user_timestamp("not-a-date")

    def test_utc_now_is_aware_and_second_precision(self) -> None:
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.microsecond, 0)


class FormattingTests(unittest.TestCase):
    def test_human_duration(self) -> None:
        self.assertEqual(human_duration(None), "—")
        self.assertEqual(human_duration(45), "45s")
        self.assertEqual(human_duration(90), "1m")
        self.assertEqual(human_duration(3660), "1h 1m")
        self.assertEqual(human_duration(90000), "1d 1h")

    def test_duration_minutes(self) -> None:
        self.assertEqual(duration_minutes(45), "45m")
        self.assertEqual(duration_minutes(60), "1h")
        self.assertEqual(duration_minutes(150), "2h 30m")
        self.assertEqual(duration_minutes(1440), "1 day")
        self.assertEqual(duration_minutes(2880), "2 days")

    def test_truncate(self) -> None:
        self.assertEqual(truncate("  a   b  "), "a b")
        self.assertEqual(truncate("abcdef", 6), "abcdef")
        self.assertTrue(truncate("abcdefghij", 5).endswith("…"))

    def test_format_local_handles_missing_and_invalid(self) -> None:
        self.assertEqual(format_local(None), "—")
        rendered = format_local("2026-05-01T12:00:00Z", "%Y-%m-%d %H:%M")
        self.assertRegex(rendered, r"^2026-05-01 \d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
