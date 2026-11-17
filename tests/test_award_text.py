import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from award_text import TEXT_API_FIELDS, TEXT_COLUMNS
from award_text_archive import archive_text
import award_text_archive


class FetchTextTests(unittest.TestCase):
    def test_national_defaults_and_updates_preserve_old_text(self):
        for module_name in ("nih_awards_national_fetch", "nih_awards_national_incremental_2026_fetch"):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertFalse(module.INCLUDE_TEXT_FIELDS)
                self.assertTrue(set(TEXT_API_FIELDS).isdisjoint(module.INCLUDE_FIELDS))
                with duckdb.connect(":memory:") as con:
                    con.execute(module.DDL)
                    original = {"appl_id": 1, "award_amount": 10, **{c: "old " + c for c in TEXT_COLUMNS}}
                    with patch.object(module, "INCLUDE_TEXT_FIELDS", True):
                        module.insert_records(con, [original])
                    module.insert_records(con, [{"appl_id": 1, "award_amount": 20}, {"appl_id": 2, "award_amount": 30}])
                    self.assertEqual(con.execute("SELECT award_amount, abstract_text, terms FROM nih_awards_national WHERE appl_id=1").fetchone(), (20, "old abstract_text", "old terms"))
                    self.assertEqual(con.execute("SELECT abstract_text, terms FROM nih_awards_national WHERE appl_id=2").fetchone(), (None, None))
                    with patch.object(module, "INCLUDE_TEXT_FIELDS", True):
                        module.insert_records(con, [{**original, "terms": "updated"}])
                    self.assertEqual(con.execute("SELECT terms FROM nih_awards_national WHERE appl_id=1").fetchone()[0], "updated")

    def test_ucd_excludes_all_four_and_preserves_text(self):
        module = importlib.import_module("nih_awards_fetch")
        with patch.object(module.requests, "post") as post:
            post.return_value.json.return_value = {"results": []}
            module.search_page(["test"], [2026], 0)
            self.assertEqual(set(post.call_args.kwargs["json"]["exclude_fields"]), set(TEXT_API_FIELDS))
            with patch.object(module, "INCLUDE_TEXT_FIELDS", True):
                module.search_page(["test"], [2026], 0)
                self.assertNotIn("exclude_fields", post.call_args.kwargs["json"])
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "test.duckdb")
            with patch.object(module, "INCLUDE_TEXT_FIELDS", True):
                module.load_to_duckdb([{"appl_id": 1, "terms": "keep me"}], db)
            module.load_to_duckdb([{"appl_id": 1, "award_amount": 20}], db)
            with duckdb.connect(db) as con:
                self.assertEqual(con.execute("SELECT terms, award_amount FROM ucd_awards").fetchone(), ("keep me", 20))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "source.duckdb"
        self.output = Path(self.temp.name) / "archive"
        with duckdb.connect(str(self.db)) as con:
            con.execute("CREATE TABLE nih_awards_national (appl_id BIGINT PRIMARY KEY, fiscal_year INTEGER, abstract_text VARCHAR, phr_text VARCHAR, terms VARCHAR, pref_terms VARCHAR)")
            con.execute("INSERT INTO nih_awards_national VALUES (1, 2026, 'α research', NULL, 'term', ''), (2, 2025, NULL, NULL, NULL, NULL)")

    def test_roundtrip_and_retention(self):
        paths = []
        self.output.mkdir()
        unrelated = self.output / "unrelated.parquet"
        unrelated.write_bytes(b"preserve")
        for _ in range(7):
            result = archive_text(self.db, self.output)
            paths.append(Path(result["file"]))
        self.assertEqual(result["retained_snapshots"], 5)
        self.assertFalse(paths[0].exists())
        self.assertFalse(paths[1].exists())
        self.assertTrue(all(p.exists() for p in paths[2:]))
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(list(self.output.glob("award-text-*.parquet"))), 5)
        self.assertEqual(json.loads((self.output / "latest.json").read_text())["file"], paths[-1].name)
        with duckdb.connect(str(self.db)) as con:
            self.assertEqual(con.execute("SELECT * FROM nih_awards_national ORDER BY appl_id").fetchall(), con.execute("SELECT * FROM read_parquet(?) ORDER BY appl_id", [str(paths[-1])]).fetchall())

    def test_failed_verification_does_not_rotate(self):
        original = archive_text(self.db, self.output, keep=1)
        real = award_text_archive.fingerprint
        calls = 0
        def broken(con, relation):
            nonlocal calls
            calls += 1
            values = real(con, relation)
            if calls == 2:
                values[0] += 1
            return values
        with patch.object(award_text_archive, "fingerprint", side_effect=broken):
            with self.assertRaisesRegex(ValueError, "verification failed"):
                archive_text(self.db, self.output, keep=1)
        self.assertTrue(Path(original["file"]).exists())
        self.assertEqual(len(list(self.output.glob("award-text-*.parquet"))), 1)
        self.assertEqual(list(self.output.glob("*.partial")), [])

    def test_empty_source_does_not_rotate(self):
        original = archive_text(self.db, self.output)
        with duckdb.connect(str(self.db)) as con:
            con.execute("DELETE FROM nih_awards_national")
        with self.assertRaisesRegex(ValueError, "No source text"):
            archive_text(self.db, self.output)
        self.assertTrue(Path(original["file"]).exists())

    def test_in_use_snapshot_is_skipped_then_retired(self):
        first = Path(archive_text(self.db, self.output, keep=1)["file"])
        real_unlink = Path.unlink
        def windows_unlink(path, *args, **kwargs):
            if path == first:
                raise PermissionError("in use by another process")   # what Windows does
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", windows_unlink):
            result = archive_text(self.db, self.output, keep=1)
        self.assertEqual(result["in_use_not_retired"], [first.name])
        self.assertTrue(first.exists() and first.with_suffix(".json").exists())
        later = archive_text(self.db, self.output, keep=1)
        self.assertIn(first.name, later["retired"])
        self.assertEqual(len(list(self.output.glob("award-text-*.parquet"))), 1)

    def test_concurrent_export_is_refused(self):
        self.output.mkdir()
        with award_text_archive.export_lock(self.output / ".archive.lock"):
            with self.assertRaises(OSError):
                archive_text(self.db, self.output)


if __name__ == "__main__":
    unittest.main()
