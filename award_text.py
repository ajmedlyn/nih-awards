"""Shared optional text fields and partial updates for NIH fetchers."""

import pandas as pd

TEXT_API_FIELDS = ("AbstractText", "PhrText", "Terms", "PrefTerms")
TEXT_COLUMNS = ("abstract_text", "phr_text", "terms", "pref_terms")


def upsert_records(con, table, records, flatten_record, include_text=False):
    """Update supplied metadata without nulling text omitted from the request."""
    rows = []
    for record in records:
        row = flatten_record(record)
        if not include_text:
            for column in TEXT_COLUMNS:
                row.pop(column, None)
        rows.append(row)
    if not rows:
        return
    # API pages can repeat an application; retain the last observation.
    frame = pd.DataFrame(rows).drop_duplicates(subset=["appl_id"], keep="last")
    quote = lambda name: '"' + name.replace('"', '""') + '"'
    columns = ", ".join(quote(c) for c in frame.columns)
    assignments = ", ".join(
        f"{quote(c)} = EXCLUDED.{quote(c)}" for c in frame.columns if c != "appl_id"
    )
    con.register("_nih_incoming", frame)
    try:
        con.execute(
            f"INSERT INTO {quote(table)} ({columns}) SELECT {columns} FROM _nih_incoming "
            f"ON CONFLICT (appl_id) DO UPDATE SET {assignments}"
        )
    finally:
        con.unregister("_nih_incoming")
