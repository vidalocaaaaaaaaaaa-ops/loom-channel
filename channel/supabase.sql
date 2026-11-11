-- Optional mirror for the channel queue. Run in the Supabase SQL editor.
-- The pipeline works fine without it; state.json in the repo is the source of truth.

create table if not exists channel_state (
  id          text primary key default 'current',
  updated_at  timestamptz not null default now(),
  data        jsonb not null
);

create table if not exists episodes (
  slug         text primary key,
  series       text not null,
  series_title text,
  part         int  not null,
  title        text,
  status       text not null default 'queued',   -- queued | rendered | published | skipped
  video_path   text,
  cover_path   text,
  qc           text,
  youtube      jsonb,
  video_id     text,
  video_url    text,
  rendered_at  timestamptz,
  published_at timestamptz
);

create index if not exists episodes_series_part on episodes (series, part);

-- read-only access for an anon dashboard key
alter table channel_state enable row level security;
alter table episodes      enable row level security;

drop policy if exists "dashboard read" on channel_state;
create policy "dashboard read" on channel_state for select using (true);

drop policy if exists "dashboard read" on episodes;
create policy "dashboard read" on episodes for select using (true);
