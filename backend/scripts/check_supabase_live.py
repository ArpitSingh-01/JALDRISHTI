"""Live check: can the backend reach Supabase, and does the runs table exist?"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from jaldrishti.api import store  # noqa: E402

print("configured:", store.is_configured())
c = store.client()
if c is None:
    print("client: NONE (credentials missing or supabase-py not installed)")
else:
    try:
        resp = c.table("runs").select("run_id").limit(3).execute()
        print("runs table: OK, rows:", len(resp.data))
    except Exception as exc:
        print(f"runs table: FAILED - {type(exc).__name__}: {exc}")
    try:
        buckets = c.storage.list_buckets()
        names = [b.name for b in buckets] if buckets else []
        print("storage buckets:", names)
    except Exception as exc:
        print(f"storage: FAILED - {type(exc).__name__}: {exc}")
