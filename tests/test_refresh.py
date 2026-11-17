"""Tests for the safety checks in refresh_and_normalize.py and the incremental fetch."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb

import nih_awards_national_incremental_2026_fetch as incremental
import refresh_and_normalize as refresh

INSERT = """
INSERT INTO nih_awards_national (
    appl_id, subproject_id, fiscal_year, project_num, core_project_num, activity_code,
    award_amount, award_notice_date, project_start_date, project_end_date, agency_code,
    agency_ic_admin_code, org_name, org_state, org_duns, geo_lat, geo_lon, project_title,
    pis_json, agency_ic_fundings_json, spending_categories_json, spending_categories_desc,
    abstract_text, phr_text)
VALUES (?, NULL, 2026, ?, ?, 'R01', 100000, '2026-01-15T00:00:00', '2025-07-01T00:00:00',
        '2030-06-30T00:00:00', 'NIH', 'CA', 'TEST UNIVERSITY', 'CO', '[123456789]', 39.7, -104.8,
        'A test project',
        '[{"profile_id": 1, "first_name": "Ada", "last_name": "Test", "is_contact_pi": true}]',
        '[{"fy": 2026, "code": "CA", "name": "National Cancer Institute", "total_cost": 100000}]',
        '[132]', 'Cancer', ?, NULL)
"""


class RefreshSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "test.duckdb")
        with duckdb.connect(self.db) as con:
            con.execute(incremental.DDL)
            self.add_award(con, 1, abstract="An abstract")
            self.add_award(con, 2, abstract=None)

    def add_award(self, con, appl_id, abstract):
        con.execute(INSERT, [appl_id, f"1R01CA00000{appl_id}-01", f"R01CA00000{appl_id}", abstract])

    def normalize(self, build):
        with duckdb.connect(self.db) as con, redirect_stdout(io.StringIO()):
            return refresh.run_normalize(con, build)

    def test_missing_awards_stop_the_rebuild(self):
        # The completeness check reports a gap when NIH has more awards than the table.
        with duckdb.connect(self.db) as con, redirect_stdout(io.StringIO()), \
             patch.object(incremental, "FISCAL_YEARS", [2026]), \
             patch.object(incremental, "api_total", return_value=5), \
             patch.object(incremental.time, "sleep"):
            self.assertEqual(incremental.check_completeness(con), 3)

        # Exit code 2 from the fetch stops refresh_and_normalize before any table is built.
        with patch.object(refresh.subprocess, "run") as run, \
             patch.object(refresh, "require_existing_db"), \
             patch.object(sys, "argv", ["refresh_and_normalize.py", "--db", self.db]), \
             redirect_stdout(io.StringIO()) as out:
            run.return_value.returncode = incremental.EXIT_MISSING_AWARDS
            self.assertEqual(refresh.main(), 1)
        self.assertIn("MISSING AWARDS", out.getvalue())
        with duckdb.connect(self.db) as con:
            built = con.execute("SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'award_fact'").fetchone()[0]
        self.assertEqual(built, 0)

    def test_integrity_failure_rolls_back_every_table(self):
        self.assertTrue(self.normalize(refresh.BUILD_ORDER))
        with duckdb.connect(self.db) as con:
            before = con.execute("SELECT COUNT(*) FROM award_fact").fetchone()[0]
            # A duplicated source row makes award_fact's ApplicationID non-unique.
            con.execute("CREATE OR REPLACE TABLE nih_awards_national AS "
                        "SELECT * FROM nih_awards_national UNION ALL "
                        "(SELECT * FROM nih_awards_national WHERE appl_id = 1)")
        self.assertFalse(self.normalize(refresh.BUILD_ORDER))
        with duckdb.connect(self.db) as con:
            after = con.execute("SELECT COUNT(*) FROM award_fact").fetchone()[0]
        self.assertEqual(after, before)   # previous version kept

    def test_award_text_warning_when_not_rebuilt(self):
        self.assertTrue(self.normalize(refresh.BUILD_ORDER + refresh.TEXT_BUILD))
        with duckdb.connect(self.db) as con:
            self.add_award(con, 3, abstract="A newer abstract")
            with redirect_stdout(io.StringIO()) as out:
                refresh.check_award_text(con, rebuilt=False)
            self.assertIn("award_text not rebuilt", out.getvalue())
            with redirect_stdout(io.StringIO()) as out:
                refresh.check_award_text(con, rebuilt=True)
            self.assertEqual(out.getvalue(), "")



class StagingMergeTests(unittest.TestCase):
    """The incremental fetch writes to a local staging file, then merges once."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "main.duckdb"
        self.staging = Path(self.temp.name) / "main_staging.duckdb"
        patcher = patch.object(incremental, "STAGING_PATH", self.staging)
        patcher.start()
        self.addCleanup(patcher.stop)
        with duckdb.connect(str(self.db)) as con:
            con.execute(incremental.DDL)
            con.execute("INSERT INTO nih_awards_national (appl_id, fiscal_year, award_amount, abstract_text) "
                        "VALUES (1, 2026, 100, 'old abstract')")

    def stage(self, rows, include_text):
        con = incremental.open_staging(include_text)
        con.executemany("INSERT INTO nih_awards_national (appl_id, fiscal_year, award_amount, abstract_text) "
                        "VALUES (?, 2026, ?, ?)", rows)
        con.close()

    def main_rows(self):
        with duckdb.connect(str(self.db)) as con:
            return con.execute("SELECT appl_id, award_amount, abstract_text FROM nih_awards_national "
                               "ORDER BY appl_id").fetchall()

    def merge(self):
        with redirect_stdout(io.StringIO()):
            return incremental.merge_staging(self.db, self.staging)

    def test_merge_updates_inserts_and_keeps_text_when_not_fetched(self):
        self.stage([(1, 200, None), (2, 300, None)], include_text=False)
        self.assertEqual(self.merge(), 2)
        self.assertEqual(self.main_rows(), [(1, 200, "old abstract"), (2, 300, None)])
        self.assertFalse(self.staging.exists())

    def test_merge_with_text_updates_text(self):
        self.stage([(1, 200, "new abstract")], include_text=True)
        self.merge()
        self.assertEqual(self.main_rows(), [(1, 200, "new abstract")])

    def test_failed_merge_leaves_main_untouched_and_keeps_staging(self):
        self.stage([(1, 200, None), (2, 300, None)], include_text=False)
        real = incremental.merge_sql
        broken = lambda columns: real(columns) + "; SELECT error('network dropped')"
        with patch.object(incremental, "merge_sql", broken), self.assertRaises(duckdb.Error):
            self.merge()
        self.assertEqual(self.main_rows(), [(1, 100, "old abstract")])
        self.assertTrue(self.staging.exists())
        self.merge()   # the next run recovers it
        self.assertEqual(self.main_rows(), [(1, 200, "old abstract"), (2, 300, None)])

    def test_next_run_merges_leftover_staging_first(self):
        self.stage([(5, 500, None)], include_text=False)
        with patch.object(incremental, "DB_PATH", str(self.db)), \
             patch.object(incremental.db_config, "require_existing_db"), \
             patch.object(incremental, "FISCAL_YEARS", []), \
             patch.object(incremental, "check_completeness", return_value=0), \
             patch.object(sys, "argv", ["fetch"]), redirect_stdout(io.StringIO()):
            self.assertEqual(incremental.main(), 0)
        self.assertIn((5, 500, None), self.main_rows())
        self.assertFalse(self.staging.exists())


if __name__ == "__main__":
    unittest.main()
