create table if not exists public.profiles (
  user_id    bigint primary key,
  username   text,
  sex        text not null,
  age        integer not null,
  height     double precision not null,
  weight     double precision not null,
  activity   integer not null,
  bmr        double precision not null,
  tdee       double precision not null,
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles_read"
  on public.profiles for select
  to anon, authenticated
  using (true);

create policy "profiles_write"
  on public.profiles for insert
  to anon, authenticated
  with check (true);

create policy "profiles_update"
  on public.profiles for update
  to anon, authenticated
  using (true)
  with check (true);

create policy "profiles_delete"
  on public.profiles for delete
  to anon, authenticated
  using (true);
