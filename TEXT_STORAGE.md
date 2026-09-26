# Award text and Parquet snapshots

All three fetchers now exclude `abstract_text`, `phr_text`, `terms`, and
`pref_terms` by default. Existing stored text is preserved when metadata is
refreshed. New awards have NULL text unless explicitly requested.

From the project directory (virtual-environment activation is optional):

```bash
./venv/bin/python nih_awards_national_incremental_2026_fetch.py
```

To download research text as well:

```bash
./venv/bin/python nih_awards_national_incremental_2026_fetch.py --include-text
```

The same flag works with `nih_awards_national_fetch.py` and `nih_awards_fetch.py`.
The full fetcher's existing resume setting still skips completed batches;
enabling text does not automatically backfill text in batches it skips.
The UCD fetcher now upserts into its existing table rather than dropping it,
so text-free refreshes do not erase previously collected text.

## Archive existing text

Close DBeaver's connection to this database before running the exporter.

```bash
./venv/bin/python award_text_archive.py
```

This exports `appl_id`, `fiscal_year`, and the four text columns directly to
Zstandard-compressed Parquet in `data/award_text/`. It avoids loading the corpus
into pandas and uses a 2 GB DuckDB memory limit, two threads, and up to 8 GB of
temporary disk space. The memory setting is a DuckDB budget, not a guarantee
that total process memory cannot exceed it.

The exporter verifies the row counts, text lengths, and aggregate row hashes
before publishing each snapshot. `latest.json` identifies the newest verified
file. After a successful export, only the newest five snapshots are retained.
Older snapshots are permanently deleted; the exporter never rotates unrelated
files. There can temporarily be a sixth copy while a new export is verified.
An empty-text export is rejected without retiring existing snapshots.

Five copies means five complete versions of the text corpus, not five awards.
To retain fewer, use `--keep 2`. Retention runs when you run the exporter; it
is not a scheduled job. Five snapshots on one disk are not an off-device backup.

## Read the text for data mining

Read the one file named in `latest.json`; reading every snapshot together would
repeat awards across versions.

```python
import json
from pathlib import Path
import duckdb

folder = Path("data/award_text")
latest = json.loads((folder / "latest.json").read_text())
con = duckdb.connect("nih_awards.duckdb", read_only=True)
con.read_parquet(str(folder / latest["file"])).create_view("award_text")
result = con.execute("""
    SELECT af.ApplicationID, af.TotalCosts, txt.abstract_text, txt.terms
    FROM award_fact af
    JOIN award_text txt ON txt.appl_id = af.ApplicationID
    WHERE af.ApplicationID = ?
""", [123456]).fetchall()  # replace with a real application ID
```

## Database size and a later migration

Exporting is non-destructive and does not shrink the current database. The
existing text remains available to the fetchers and SQL queries. To actually
move text out, a separate migration must verify a full archive, remove text
from the analytical database, and compact it into a fresh DuckDB file while
preserving all other tables, views, and constraints.

Do not clear the source text and keep running this full-source exporter against
partial newly fetched text: that would produce incomplete historical snapshots.
A future external-text refresh must merge new observations into the previous
Parquet corpus by `appl_id` before applying five-snapshot retention.

The database, journal/spill files, Parquet files, and archive directory are
excluded from Git. Keep those exclusions in place and avoid force-adding data.
