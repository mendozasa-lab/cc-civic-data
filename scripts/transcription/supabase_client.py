"""Shared Supabase client for transcription scripts. Uses service role key for writes."""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(url, key)


def fetch_all(client: Client, table: str, query_fn=None, page_size: int = 1000) -> list:
    """Paginate through a Supabase table query until all records are returned."""
    all_data = []
    offset = 0
    while True:
        q = client.table(table).select("*") if query_fn is None else query_fn()
        result = q.range(offset, offset + page_size - 1).execute()
        all_data.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_data


def upsert_batch(client: Client, table: str, rows: list, batch_size: int = 500, on_conflict: str = None) -> None:
    """Upsert rows in batches."""
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        q = client.table(table).upsert(batch, on_conflict=on_conflict) if on_conflict else client.table(table).upsert(batch)
        q.execute()
