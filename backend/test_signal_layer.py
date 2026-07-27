import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dedup
import migrate
import timestamps
from timestamps import PRECISION_DAY, PRECISION_EXACT, PRECISION_UNKNOWN, parse_published


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


class ParsePublishedTests(unittest.TestCase):
    def test_iso_with_time_is_exact_and_utc(self):
        parsed, precision = parse_published("2026-07-15T10:30:00Z", now=NOW)
        self.assertEqual(precision, PRECISION_EXACT)
        self.assertEqual(parsed, datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc))

    def test_iso_offset_is_preserved_as_an_instant(self):
        parsed, _ = parse_published("2026-07-15T10:30:00+03:00", now=NOW)
        self.assertEqual(parsed, datetime(2026, 7, 15, 7, 30, tzinfo=timezone.utc))

    def test_date_only_is_day_precision_not_midnight_exact(self):
        parsed, precision = parse_published("2026-07-15", now=NOW)
        self.assertEqual(precision, PRECISION_DAY)
        self.assertEqual(parsed, datetime(2026, 7, 15, tzinfo=timezone.utc))

    def test_rfc2822_feed_dates_parse(self):
        parsed, precision = parse_published("Tue, 15 Jul 2026 10:30:00 +0000", now=NOW)
        self.assertEqual(precision, PRECISION_EXACT)
        self.assertEqual(parsed, datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc))

    def test_naive_datetime_string_is_assumed_utc(self):
        parsed, precision = parse_published("2026-07-15 10:30:00", now=NOW)
        self.assertEqual(precision, PRECISION_EXACT)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_human_formats_parse_as_day(self):
        for raw in ("July 15, 2026", "15 Jul 2026", "2026/07/15", "20260715"):
            parsed, precision = parse_published(raw, now=NOW)
            self.assertEqual(precision, PRECISION_DAY, raw)
            self.assertEqual(parsed.date(), date(2026, 7, 15), raw)

    def test_leading_iso_date_inside_longer_string(self):
        parsed, precision = parse_published("2026-07-15 — updated later", now=NOW)
        self.assertEqual(precision, PRECISION_DAY)
        self.assertEqual(parsed.date(), date(2026, 7, 15))

    def test_datetime_and_date_objects_pass_through(self):
        self.assertEqual(
            parse_published(datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc), now=NOW),
            (datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc), PRECISION_EXACT),
        )
        parsed, precision = parse_published(date(2026, 7, 15), now=NOW)
        self.assertEqual((parsed.date(), precision), (date(2026, 7, 15), PRECISION_DAY))

    def test_unusable_values_are_unknown_and_carry_no_date(self):
        for raw in (None, "", "   ", "n/a", "yesterday", "Coming soon", "12345"):
            parsed, precision = parse_published(raw, now=NOW)
            self.assertEqual(precision, PRECISION_UNKNOWN, repr(raw))
            self.assertIsNone(parsed, repr(raw))

    def test_epoch_and_footer_years_are_rejected_as_implausible(self):
        for raw in ("1970-01-01T00:00:00Z", "1900-01-01"):
            parsed, precision = parse_published(raw, now=NOW)
            self.assertEqual(precision, PRECISION_UNKNOWN, raw)
            self.assertIsNone(parsed, raw)

    def test_far_future_rejected_but_small_feed_skew_accepted(self):
        far, far_precision = parse_published("2030-01-01T00:00:00Z", now=NOW)
        self.assertIsNone(far)
        self.assertEqual(far_precision, PRECISION_UNKNOWN)

        skewed = (NOW + timedelta(hours=6)).isoformat()
        parsed, precision = parse_published(skewed, now=NOW)
        self.assertIsNotNone(parsed)
        self.assertEqual(precision, PRECISION_EXACT)

    def test_is_trendable_excludes_unknown_only(self):
        self.assertTrue(timestamps.is_trendable(PRECISION_EXACT))
        self.assertTrue(timestamps.is_trendable(PRECISION_DAY))
        self.assertFalse(timestamps.is_trendable(PRECISION_UNKNOWN))
        self.assertFalse(timestamps.is_trendable(None))


WIRE_STORY = (
    "The manufacturer confirmed on Tuesday that it will expand production of its "
    "electric sedan at the Stuttgart plant, adding a second shift by the end of "
    "the quarter. Executives said the decision follows stronger than expected "
    "demand across European markets, where order books have lengthened to nine "
    "weeks. The company also reiterated its target of building three hundred "
    "thousand units annually by the end of the decade, a figure analysts have "
    "described as ambitious given current battery supply constraints."
)

# Same wire copy as a second outlet would carry it: house style tweaks, an added
# attribution line, a dropped clause. This must still collapse into one story.
WIRE_STORY_REPRINT = (
    "The manufacturer confirmed on Tuesday that it will expand production of its "
    "electric sedan at the Stuttgart plant, adding a second shift by the end of "
    "the quarter. Executives said the decision follows stronger than expected "
    "demand across European markets, where order books have lengthened to nine "
    "weeks. The company also reiterated its target of building three hundred "
    "thousand units annually by the end of the decade, a figure analysts have "
    "called ambitious given current battery supply constraints. Reuters contributed."
)

DIFFERENT_STORY = (
    "Owners of the compact hatchback continue to report that the driver seat "
    "upholstery wears through at the bolster within the first two years, and "
    "several have posted photographs of cracked panels after a single summer. "
    "The dealer network has offered goodwill replacements in some regions but "
    "declined them elsewhere, which has become its own source of frustration "
    "among the ownership community discussing the problem on forums this month."
)


class MinHashTests(unittest.TestCase):
    def test_identical_text_signs_identically(self):
        self.assertEqual(dedup.signature(WIRE_STORY), dedup.signature(WIRE_STORY))
        self.assertEqual(dedup.estimated_jaccard(*[dedup.signature(WIRE_STORY)] * 2), 1.0)

    def test_signature_is_stable_across_processes(self):
        """Guards the determinism promise: never Python's salted hash()."""
        module_dir = str(__import__("pathlib").Path(dedup.__file__).parent)
        code = (
            "import sys; sys.path.insert(0, %r); import dedup; "
            "print(dedup.signature(%r))" % (module_dir, WIRE_STORY)
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True
            ).stdout.strip()
            for _ in range(2)
        }
        self.assertEqual(len(runs), 1, f"signature varied across processes: {runs}")
        self.assertEqual(runs.pop(), str(dedup.signature(WIRE_STORY)))

    def test_syndicated_reprint_is_a_duplicate(self):
        left = dedup.signature(WIRE_STORY)
        right = dedup.signature(WIRE_STORY_REPRINT)
        score = dedup.estimated_jaccard(left, right)
        # Measured 0.82 (exact Jaccard 0.86) on a 79-token body — the case a
        # fixed 3-bit SimHash threshold got wrong at 13 bits of distance.
        self.assertGreater(score, 0.75, f"similarity {score} lower than expected")
        self.assertTrue(dedup.is_duplicate(left, right))

    def test_unrelated_story_is_not_a_duplicate(self):
        left = dedup.signature(WIRE_STORY)
        right = dedup.signature(DIFFERENT_STORY)
        self.assertLess(dedup.estimated_jaccard(left, right), 0.1)
        self.assertFalse(dedup.is_duplicate(left, right))

    def test_threshold_has_margin_on_both_sides(self):
        reprint = dedup.estimated_jaccard(
            dedup.signature(WIRE_STORY), dedup.signature(WIRE_STORY_REPRINT)
        )
        unrelated = dedup.estimated_jaccard(
            dedup.signature(WIRE_STORY), dedup.signature(DIFFERENT_STORY)
        )
        self.assertGreater(reprint, dedup.SIMILARITY_THRESHOLD)
        self.assertLess(unrelated, dedup.SIMILARITY_THRESHOLD)

    def test_short_text_is_not_fingerprinted(self):
        self.assertIsNone(dedup.signature("too short to mean anything"))
        self.assertIsNone(dedup.fingerprint("Headline", "still far too short"))

    def test_fingerprint_requires_some_content(self):
        self.assertIsNone(dedup.fingerprint(None, None))
        self.assertIsNotNone(dedup.fingerprint("A headline", WIRE_STORY))

    def test_estimate_degrades_gracefully_on_bad_input(self):
        self.assertEqual(dedup.estimated_jaccard([], [1, 2]), 0.0)
        self.assertEqual(dedup.estimated_jaccard([1, 2], [1]), 0.0)


class BandingTests(unittest.TestCase):
    def test_signature_values_fit_postgres_integer(self):
        for value in dedup.signature(WIRE_STORY):
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 0x7FFFFFFF)

    def test_band_keys_fit_postgres_bigint(self):
        keys = dedup.band_keys(dedup.signature(WIRE_STORY))
        self.assertEqual(len(keys), dedup.BAND_COUNT)
        for key in keys:
            self.assertGreaterEqual(key, 0)
            self.assertLess(key, 2**63)

    def test_signature_length_divides_into_bands(self):
        self.assertEqual(dedup.BAND_COUNT * dedup.BAND_ROWS, dedup.SIGNATURE_SIZE)
        self.assertEqual(len(dedup.signature(WIRE_STORY)), dedup.SIGNATURE_SIZE)

    def test_duplicates_share_bands_and_unrelated_pairs_do_not(self):
        """LSH recall: the indexed lookup must actually surface true duplicates."""
        base = dedup.band_keys(dedup.signature(WIRE_STORY))
        reprint = dedup.band_keys(dedup.signature(WIRE_STORY_REPRINT))
        unrelated = dedup.band_keys(dedup.signature(DIFFERENT_STORY))
        self.assertTrue(set(base) & set(reprint), "reprint would never be looked up")
        self.assertFalse(set(base) & set(unrelated))

    def test_band_keys_are_deterministic(self):
        sig = dedup.signature(WIRE_STORY)
        self.assertEqual(dedup.band_keys(sig), dedup.band_keys(sig))


@contextmanager
def _migrations(*filenames, baseline="-- baseline\n"):
    """Point the runner at a throwaway migrations directory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_file = root / "schema.sql"
        baseline_file.write_text(baseline, encoding="utf-8")
        migrations_dir = root / "migrations"
        migrations_dir.mkdir()
        for name in filenames:
            (migrations_dir / name).write_text(f"-- {name}\n", encoding="utf-8")

        original = (migrate.BASELINE_FILE, migrate.MIGRATIONS_DIR)
        migrate.BASELINE_FILE, migrate.MIGRATIONS_DIR = baseline_file, migrations_dir
        try:
            yield
        finally:
            migrate.BASELINE_FILE, migrate.MIGRATIONS_DIR = original


class MigrationDiscoveryTests(unittest.TestCase):
    def test_baseline_comes_first_then_numeric_order(self):
        with _migrations("0010_ten.sql", "0002_two.sql", "0003_three.sql"):
            versions = [m.version for m in migrate.discover()]
        self.assertEqual(
            versions, ["0001_baseline", "0002_two", "0003_three", "0010_ten"]
        )

    def test_zero_padding_keeps_ten_after_two(self):
        """Filename sort must not put 0010 before 0002."""
        with _migrations("0002_two.sql", "0010_ten.sql"):
            versions = [m.version for m in migrate.discover()]
        self.assertLess(versions.index("0002_two"), versions.index("0010_ten"))

    def test_non_sql_and_dotfiles_are_ignored(self):
        with _migrations("0002_two.sql", ".hidden.sql", "notes.md"):
            versions = [m.version for m in migrate.discover()]
        self.assertEqual(versions, ["0001_baseline", "0002_two"])

    def test_malformed_filename_is_rejected_loudly(self):
        for bad in ("2_two.sql", "0002-two.sql", "0002_Two.sql", "two.sql"):
            with self.subTest(bad=bad), _migrations(bad):
                with self.assertRaises(migrate.MigrationError):
                    migrate.discover()

    def test_0001_is_reserved_for_the_baseline(self):
        with _migrations("0001_something.sql"):
            with self.assertRaises(migrate.MigrationError):
                migrate.discover()

    def test_duplicate_numbers_are_rejected(self):
        with _migrations("0002_two.sql", "0002_also_two.sql"):
            with self.assertRaises(migrate.MigrationError):
                migrate.discover()

    def test_checksum_tracks_content_not_filename(self):
        with _migrations("0002_two.sql"):
            first = {m.version: m.checksum for m in migrate.discover()}
            path = migrate.MIGRATIONS_DIR / "0002_two.sql"
            path.write_text("-- 0002_two.sql\n-- edited\n", encoding="utf-8")
            second = {m.version: m.checksum for m in migrate.discover()}
        self.assertNotEqual(first["0002_two"], second["0002_two"])
        self.assertEqual(first["0001_baseline"], second["0001_baseline"])

    def test_real_migrations_directory_is_wellformed(self):
        """The migrations actually shipped in this repo must discover cleanly."""
        versions = [m.version for m in migrate.discover()]
        self.assertEqual(versions[0], "0001_baseline")
        self.assertEqual(len(versions), len(set(versions)))
        for migration in migrate.discover():
            self.assertTrue(migration.sql.strip(), f"{migration.version} is empty")
            self.assertEqual(len(migration.checksum), 64)


if __name__ == "__main__":
    unittest.main()
