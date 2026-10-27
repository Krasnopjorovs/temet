-- Миграция для баз, созданных версией 0.1.0 (на свежей установке — no-op).
alter table rule        add column if not exists label    jsonb not null default '{}';
alter table calibration add column if not exists syn_hash text;
alter table profile     add column if not exists syn_hash text;
alter table rule        add column if not exists covers   text[] not null default '{}';
alter table report_module add column if not exists kinds text[] not null default '{}';
