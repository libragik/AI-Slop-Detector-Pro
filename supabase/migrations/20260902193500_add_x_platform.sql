-- Keep existing deployments compatible with X status analysis. Fresh installs
-- already include x in the original table definition; recreating this named
-- constraint is harmless when migrations run from the beginning.
alter table public.video_analyses
  drop constraint if exists video_analyses_platform_check;

alter table public.video_analyses
  add constraint video_analyses_platform_check
  check (platform in ('youtube', 'tiktok', 'instagram', 'x', 'upload'));
