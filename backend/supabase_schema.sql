-- JALDRISHTI Supabase schema — run once in the Supabase SQL editor.
-- Mirrors api/store.py: RUNS_TABLE = "runs", ARTIFACTS_BUCKET = "jaldrishti".

create table if not exists public.runs (
    run_id            text primary key,
    status            text,
    area              text,
    dx_m              double precision,
    duration_s        double precision,
    wall_time_s       double precision,
    submitted_utc     text,
    started_utc       text,
    finished_utc      text,
    headline          text,
    presentable       boolean,
    peak_depth_m      double precision,
    flooded_area_km2  double precision,
    first_arrival_min double precision,
    exposed_people    double precision,
    has_bundle        boolean,
    raw               jsonb,
    updated_at        timestamptz not null default now()
);

create index if not exists runs_finished_idx on public.runs (finished_utc desc);

-- The service role writes via the API; anon clients get nothing.
alter table public.runs enable row level security;

-- Storage bucket for export artifacts (GeoTIFF / SHP / KML / PDF / ...).
-- insert ... on conflict keeps this re-runnable.
insert into storage.buckets (id, name, public)
values ('jaldrishti', 'jaldrishti', false)
on conflict (id) do nothing;
