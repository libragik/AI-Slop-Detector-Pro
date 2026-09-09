create extension if not exists pgcrypto with schema extensions;

create table public.video_analyses (
  id uuid primary key default extensions.gen_random_uuid(),
  canonical_key text not null unique,
  canonical_url text,
  platform text not null check (platform in ('youtube', 'tiktok', 'instagram', 'x', 'upload')),
  platform_video_id text not null,
  status text not null default 'complete' check (status in ('pending', 'complete', 'failed')),
  analyzer_version text not null,
  final_score integer not null check (final_score between 1 and 99),
  evidence_label text not null,
  result_json jsonb not null,
  error_message text,
  analyzed_at timestamptz not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

comment on table public.video_analyses is
  'Versioned, expiring AI Slop Detector results. Original media is never stored here.';
comment on column public.video_analyses.canonical_key is
  'Stable platform:id or upload:sha256 key used to avoid duplicate model calls.';

create index video_analyses_expires_at_idx
  on public.video_analyses (expires_at);

alter table public.video_analyses enable row level security;

-- This cache is private to the server. The service role bypasses RLS; browser
-- roles receive no policy and no table privileges.
revoke all on table public.video_analyses from anon, authenticated;
grant select, insert, update, delete on table public.video_analyses to service_role;
