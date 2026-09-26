create table public.push_subs (
  endpoint text primary key,
  p256dh text not null,
  auth text not null,
  ua text,
  created_at timestamptz not null default now(),
  last_ok timestamptz,
  last_test timestamptz,
  fails int not null default 0
);
create table public.push_keys (
  id int primary key default 1 check (id = 1),
  public_key text not null,
  private_jwk jsonb not null,
  subject text not null
);
create table public.push_state (
  id int primary key default 1 check (id = 1),
  generated text,
  snap jsonb,
  updated_at timestamptz not null default now()
);
create table public.push_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  title text,
  body text,
  sent int,
  failed int,
  removed int
);
-- RLS on, no policies: only the edge function (service role) touches these.
alter table public.push_subs enable row level security;
alter table public.push_keys enable row level security;
alter table public.push_state enable row level security;
alter table public.push_log enable row level security;
