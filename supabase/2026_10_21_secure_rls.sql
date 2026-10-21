-- =====================================================================
-- Безпека доступу: Telegram initData -> JWT -> RLS
-- Дата: 2026-10-21
-- Виконати в Supabase SQL Editor (роль postgres).
--
-- Передумова: на Vercel вже є змінна SUPABASE_JWT_SECRET,
-- інакше ендпоїнт /auth не зможе випустити підписаний токен.
--
-- Порядок дій:
--   1) додати SUPABASE_JWT_SECRET у Vercel (Settings -> Env) і задеплоїти;
--   2) перевірити https://<домен>/auth (має повернути token, rls_ok: true);
--   3) виконати цей SQL.
-- =====================================================================

begin;

-- ---------------------------------------------------------------------
-- 1. Довідкові функції
-- ---------------------------------------------------------------------
-- telegram id із JWT (claim telegram_id), null для неавторизованих запитів
create or replace function public.tg_uid() returns bigint
language sql stable
as $$
  select nullif(
    coalesce(
      (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'telegram_id'),
      ''
    ), ''
  )::bigint;
$$;

-- чи належить страва користувачу (для правил на dish_items)
create or replace function public.owns_dish(p_dish_id bigint) returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.dishes d
    where d.id = p_dish_id and d.user_id = public.tg_uid()
  );
$$;

-- ---------------------------------------------------------------------
-- 2. RLS увімкнено (вже є, але повторюємо для ідемпотентності)
-- ---------------------------------------------------------------------
alter table public.profiles      enable row level security;
alter table public.products      enable row level security;
alter table public.diary_entries enable row level security;
alter table public.dishes        enable row level security;
alter table public.dish_items    enable row level security;

-- ---------------------------------------------------------------------
-- 3. Старі "відкриті" політики (using(true)) — видаляємо
-- ---------------------------------------------------------------------
do $$
declare r record;
begin
  for r in
    select tablename, policyname from pg_policies
    where schemaname = 'public'
      and tablename in ('profiles','products','diary_entries','dishes','dish_items')
  loop
    execute format('drop policy if exists %I on public.%I', r.policyname, r.tablename);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 4. Нові політики: доступ лише до власних даних
-- ---------------------------------------------------------------------
-- profiles
create policy profiles_select_own on public.profiles for select to authenticated
  using (user_id = public.tg_uid());
create policy profiles_insert_own on public.profiles for insert to authenticated
  with check (user_id = public.tg_uid());
create policy profiles_update_own on public.profiles for update to authenticated
  using (user_id = public.tg_uid()) with check (user_id = public.tg_uid());
create policy profiles_delete_own on public.profiles for delete to authenticated
  using (user_id = public.tg_uid());

-- products (user_id is null -> спільний каталог продуктів)
create policy products_select_own on public.products for select to authenticated
  using (user_id is null or user_id = public.tg_uid());
create policy products_insert_own on public.products for insert to authenticated
  with check (user_id = public.tg_uid());
create policy products_update_own on public.products for update to authenticated
  using (user_id = public.tg_uid()) with check (user_id = public.tg_uid());
create policy products_delete_own on public.products for delete to authenticated
  using (user_id = public.tg_uid());
-- спільний каталог лишається читабельним без авторизації
create policy products_select_public on public.products for select to anon
  using (user_id is null);

-- diary_entries
create policy diary_select_own on public.diary_entries for select to authenticated
  using (user_id = public.tg_uid());
create policy diary_insert_own on public.diary_entries for insert to authenticated
  with check (user_id = public.tg_uid());
create policy diary_update_own on public.diary_entries for update to authenticated
  using (user_id = public.tg_uid()) with check (user_id = public.tg_uid());
create policy diary_delete_own on public.diary_entries for delete to authenticated
  using (user_id = public.tg_uid());

-- dishes
create policy dishes_select_own on public.dishes for select to authenticated
  using (user_id is null or user_id = public.tg_uid());
create policy dishes_insert_own on public.dishes for insert to authenticated
  with check (user_id = public.tg_uid());
create policy dishes_update_own on public.dishes for update to authenticated
  using (user_id = public.tg_uid()) with check (user_id = public.tg_uid());
create policy dishes_delete_own on public.dishes for delete to authenticated
  using (user_id = public.tg_uid());
create policy dishes_select_public on public.dishes for select to anon
  using (user_id is null);

-- dish_items (через власність страви)
create policy dish_items_select_own on public.dish_items for select to authenticated
  using (public.owns_dish(dish_id));
create policy dish_items_insert_own on public.dish_items for insert to authenticated
  with check (public.owns_dish(dish_id));
create policy dish_items_update_own on public.dish_items for update to authenticated
  using (public.owns_dish(dish_id)) with check (public.owns_dish(dish_id));
create policy dish_items_delete_own on public.dish_items for delete to authenticated
  using (public.owns_dish(dish_id));

-- ---------------------------------------------------------------------
-- 5. Storage: фото належать власнику (префікс u<telegram_id>/)
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 26214400,
        array['image/*','image/jpeg','image/png','image/webp','image/gif','image/jpg'])
on conflict (id) do update set
  public = true,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

do $$
declare r record;
begin
  for r in
    select policyname from pg_policies
    where schemaname = 'storage' and tablename = 'objects'
      and policyname ilike '%photos%'
  loop
    execute format('drop policy if exists %I on storage.objects', r.policyname);
  end loop;
end $$;

create policy photos_select_own on storage.objects for select to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = 'u' || public.tg_uid()::text);
create policy photos_insert_own on storage.objects for insert to authenticated
  with check (bucket_id = 'photos' and (storage.foldername(name))[1] = 'u' || public.tg_uid()::text);
create policy photos_update_own on storage.objects for update to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = 'u' || public.tg_uid()::text)
  with check (bucket_id = 'photos' and (storage.foldername(name))[1] = 'u' || public.tg_uid()::text);
create policy photos_delete_own on storage.objects for delete to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = 'u' || public.tg_uid()::text);

commit;

-- ---------------------------------------------------------------------
-- 6. Перевірка
-- ---------------------------------------------------------------------
select tablename, policyname, cmd, roles, qual, with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('profiles','products','diary_entries','dishes','dish_items')
order by tablename, policyname;

select id, name, public from storage.buckets where id = 'photos';

select policyname, cmd, roles, qual from pg_policies
where schemaname = 'storage' and tablename = 'objects' and policyname like 'photos_%';
