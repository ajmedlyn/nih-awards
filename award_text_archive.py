"""Export complete NIH text snapshots to Parquet, retaining at most five.

This is an export, not a destructive database migration. Source text is retained.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid

import duckdb
from award_text import TEXT_COLUMNS
import db_config

try:
    import fcntl                     # macOS / Linux
except ImportError:                  # Windows
    fcntl = None
    import msvcrt

ROOT = Path(__file__).resolve().parent
SNAPSHOT = re.compile(r"award-text-\d{8}T\d{12}Z-[a-f0-9]{8}\.json")
COLUMNS = ("appl_id", "fiscal_year", *TEXT_COLUMNS)
FORMAT = "nih-award-text-v1"


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def fingerprint(con, relation):
    present = " OR ".join(f"{quote(c)} IS NOT NULL" for c in TEXT_COLUMNS)
    lengths = ", ".join(f"COALESCE(SUM(length({quote(c)})), 0)" for c in TEXT_COLUMNS)
    cols = ", ".join(quote(c) for c in COLUMNS)
    # Streaming aggregates avoid sorting / hashing millions of distinct IDs.
    return list(con.execute(
        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {present}), {lengths}, "
        f"COALESCE(SUM(CAST(hash({cols}) AS HUGEINT)), 0) FROM {relation}"
    ).fetchone())


@contextmanager
def export_lock(path):
    """Exclusive, non-blocking lock so two exports never race. Raises OSError if held."""
    with path.open("a+") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released when the file closes
            yield
            return
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def fsync_file(path):
    # Windows can only flush a file opened for writing; "ab" writes nothing.
    with path.open("ab") as handle:
        os.fsync(handle.fileno())


def write_json(path, value):
    pending = path.with_suffix(path.suffix + ".partial")
    with pending.open("x") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, path)


def archive_text(db_path, output_dir, table="nih_awards_national", keep=5):
    if not 1 <= keep <= 5:
        raise ValueError("Retention must be between 1 and 5 snapshots.")
    db_path = Path(db_path).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = {"database": str(db_path), "table": table}
    # Prevent exports / retention operations from racing each other.
    with export_lock(output_dir / ".archive.lock"):
        snapshots = []
        for path in sorted(output_dir.glob("award-text-*.json")):
            if not SNAPSHOT.fullmatch(path.name):
                continue
            metadata = json.loads(path.read_text())
            if metadata.get("format") != FORMAT or metadata.get("source") != source:
                raise ValueError("Archive directory belongs to another dataset: " + str(path))
            parquet = path.with_suffix(".parquet")
            if metadata.get("file") != parquet.name or not parquet.is_file() or parquet.is_symlink():
                raise ValueError("Missing or unsafe archive file: " + str(parquet))
            snapshots.append((path, metadata))

        con = duckdb.connect(str(db_path), read_only=True, config={
            "memory_limit": "2GB", "threads": 2,
            "preserve_insertion_order": False,
            "max_temp_directory_size": "8GB",
            "temp_directory": str(output_dir / ".spill"),
        })
        pending = None
        try:
            con.execute("BEGIN TRANSACTION")
            cols = ", ".join(quote(c) for c in COLUMNS)
            relation = f"main.{quote(table)}"
            expected = fingerprint(con, relation)
            if expected[1] == 0:
                raise ValueError("No source text found. Existing snapshots will not be rotated.")
            # Conservative estimate for UTF-8 text + writer workspace.
            needed = sum(expected[2:6]) * 4 + 1024**3
            if shutil.disk_usage(output_dir).free < needed:
                raise OSError("Insufficient free space for a safe new snapshot; no old snapshot was removed.")

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            name = f"award-text-{stamp}-{uuid.uuid4().hex[:8]}"
            parquet = output_dir / f"{name}.parquet"
            pending = output_dir / f"{name}.parquet.partial"
            con.execute(
                f"COPY (SELECT {cols} FROM {relation}) TO {literal(pending)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, ROW_GROUP_SIZE 8192)"
            )
            actual = fingerprint(con, f"read_parquet({literal(pending)})")
            if actual != expected:
                raise ValueError("Parquet verification failed; existing snapshots are unchanged.")
            con.execute("COMMIT")
            fsync_file(pending)
            os.replace(pending, parquet)
            pending = None
            metadata = {"format": FORMAT, "source": source, "file": parquet.name,
                        "created_utc": stamp, "columns": list(COLUMNS),
                        "fingerprint": expected, "bytes": parquet.stat().st_size,
                        "verification": "row count, text row count, four text lengths, sum of row hashes"}
            manifest = parquet.with_suffix(".json")
            write_json(manifest, metadata)
            write_json(output_dir / "latest.json", metadata)
            snapshots.append((manifest, metadata))
            # Only retire files created by this exporter, after verifying the replacement.
            retired, in_use = [], []
            for old, info in snapshots[:-keep]:
                old_parquet = old.with_suffix(".parquet")
                if old.is_symlink() or old_parquet.is_symlink():
                    raise ValueError("Refusing to rotate symbolic links.")
                try:
                    # Parquet first: on Windows a snapshot open in DBeaver can't be deleted.
                    # Skip it (manifest kept) and the next export retires it.
                    old_parquet.unlink()
                except PermissionError:
                    in_use.append(info["file"])
                    continue
                old.unlink()
                retired.append(info["file"])
            return {"file": str(parquet), "rows": expected[0], "rows_with_text": expected[1],
                    "GiB": round(metadata["bytes"] / 1024**3, 3),
                    "retained_snapshots": min(len(snapshots), keep) + len(in_use),
                    "retired": retired, "in_use_not_retired": in_use}
        finally:
            con.close()
            if pending is not None and pending.exists():
                pending.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=db_config.DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/award_text")
    parser.add_argument("--table", default="nih_awards_national")
    parser.add_argument("--keep", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    print(json.dumps(archive_text(args.db, args.output_dir, args.table, args.keep), indent=2))


if __name__ == "__main__":
    main()
