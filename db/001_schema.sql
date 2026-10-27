-- NeoAstro schema. Доктрина (всё астрологическое знание) — данные, не код.
create extension if not exists vector;
create extension if not exists pg_trgm;

-- ---------- Доктрина ----------
create table if not exists doctrine (
  id          serial primary key,
  code        text unique not null,
  title       text not null,
  params      jsonb not null default '{}',
  source_yaml text,
  loaded_at   timestamptz not null default now()
);

create table if not exists body (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  ord         int  not null,
  code        text not null,
  kind        text not null check (kind in ('planet','node','point','angle')),
  source      jsonb not null,
  weight      real not null,
  needs_time  boolean not null default false,
  label       jsonb not null default '{}',
  primary key (doctrine_id, code),
  unique (doctrine_id, ord)
);

create table if not exists sign (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  idx         smallint not null check (idx between 0 and 11),
  code        text not null,
  element     text not null,
  modality    text not null,
  label       jsonb not null default '{}',
  primary key (doctrine_id, idx),
  unique (doctrine_id, code)
);

create table if not exists house (
  doctrine_id int not null references doctrine(id) on delete cascade,
  num         smallint not null check (num between 1 and 12),
  class       text not null,
  label       jsonb not null default '{}',
  primary key (doctrine_id, num)
);

create table if not exists rulership (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  sign_code   text not null,
  body_code   text not null,
  role        text not null check (role in ('primary','co')),
  weight      real not null,
  primary key (doctrine_id, sign_code, body_code)
);

create table if not exists dignity (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  body_code   text not null,
  sign_code   text not null,
  kind        text not null,
  score       real not null,
  primary key (doctrine_id, body_code, sign_code)
);

create table if not exists aspect (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  code        text not null,
  angle_deg   real not null,
  orb_deg     real not null,
  weight      real not null,
  label       jsonb not null default '{}',
  primary key (doctrine_id, code)
);

create table if not exists channel_map (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  body_code   text not null,
  channel     smallint not null,
  arcana      text,
  verified    boolean not null default false,
  primary key (doctrine_id, body_code)
);

create table if not exists report_module (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  ord         int  not null,
  code        text not null,
  label       jsonb not null default '{}',
  bodies      text[] not null default '{}',
  houses      smallint[] not null default '{}',
  kinds       text[] not null default '{}',
  primary key (doctrine_id, code)
);

-- Синастрия: развёрнутые веса (receiver body x sender body x aspect)
create table if not exists synastry_dimension (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  code        text not null,
  label       jsonb not null default '{}',
  primary key (doctrine_id, code)
);

create table if not exists synastry_aspect_weight (
  doctrine_id   int  not null references doctrine(id) on delete cascade,
  dimension     text not null,
  receiver_body text not null,
  sender_body   text not null,
  aspect_code   text not null,
  weight        real not null,
  origin        text not null default 'prior',   -- prior | learned
  primary key (doctrine_id, dimension, receiver_body, sender_body, aspect_code)
);

create table if not exists synastry_overlay_weight (
  doctrine_id    int  not null references doctrine(id) on delete cascade,
  dimension      text not null,
  sender_body    text not null,
  receiver_house smallint not null check (receiver_house between 1 and 12),
  weight         real not null,
  origin         text not null default 'prior',
  primary key (doctrine_id, dimension, sender_body, receiver_house)
);

create table if not exists search_mode (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  code        text not null,
  label       jsonb not null default '{}',
  dim_weights jsonb not null,
  nash_lambda real  not null,
  primary key (doctrine_id, code)
);

create table if not exists calibration (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  key         text not null,              -- mode code или dimension code
  quantiles   double precision[] not null, -- равномерная сетка перцентилей
  n_pairs     bigint not null,
  population  text not null,              -- synthetic | profiles
  syn_hash    text,                       -- отпечаток весов; чужой отпечаток = устаревшая калибровка
  created_at  timestamptz not null default now(),
  primary key (doctrine_id, key)
);

-- Составные правила (DSL) и контент
create table if not exists rule (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  key         text not null,
  module      text not null,
  concept     text not null,
  priority    real not null default 1.0,
  condition   jsonb not null,
  label       jsonb not null default '{}',
  covers      text[] not null default '{}',
  presents    text,                      -- 'covered': показывать текст поглощённого факта этой карты
  primary key (doctrine_id, key)
);
create index if not exists rule_condition_gin on rule using gin (condition);

create table if not exists content (
  doctrine_id int  not null references doctrine(id) on delete cascade,
  key         text not null,              -- ключ факта ('sign:VENUS:AQUARIUS') или правила ('rule:RULER2_IN_8_OR_12')
  locale      text not null default 'ru',
  payload     jsonb not null,             -- {"title":..,"body":..,"shadow":..,"action":..}
  status      text not null default 'draft' check (status in ('draft','approved','rejected')),
  source      text not null,              -- откуда текст (модель/файл/автор)
  updated_at  timestamptz not null default now(),
  primary key (doctrine_id, key, locale)
);

-- ---------- Гео (офлайн, GeoNames) ----------
create table if not exists place (
  id          bigint primary key,
  name        text not null,
  ascii_name  text not null,
  alt_names   text not null default '',
  country     text not null,
  lat         double precision not null,
  lon         double precision not null,
  tz          text not null,
  population  bigint not null default 0
);
create index if not exists place_name_trgm on place using gin (ascii_name gin_trgm_ops);
create index if not exists place_alt_trgm on place using gin (alt_names gin_trgm_ops);

-- ---------- Профили соцсети ----------
create table if not exists profile (
  id                   bigserial primary key,
  doctrine_id          int  not null references doctrine(id),
  handle               text unique not null,
  birth_local          timestamp not null,
  time_known           boolean not null,
  time_uncertainty_min real not null,
  tz                   text not null,
  lat                  double precision not null,
  lon                  double precision not null,
  place_label          text not null,
  modes                text[] not null,
  synthetic            boolean not null default false,
  chart                jsonb not null,
  syn_hash             text,              -- отпечаток доктрины, с которым считаны векторы
  created_at           timestamptz not null default now()
);

-- Эмбеддинги: kind = 'x' (что человек "излучает") или 'q:<MODE>' (что ему "нужно").
-- Размерность зависит от доктрины, поэтому колонка без размерности, а HNSW-индексы
-- создаются загрузчиком доктрины как индексы по выражению v::vector(D) с фильтром kind.
create table if not exists embedding (
  profile_id  bigint not null references profile(id) on delete cascade,
  kind        text   not null,
  v           vector not null,
  primary key (profile_id, kind)
);
