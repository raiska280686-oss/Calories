-- Повна налаштування storage + колонки для фото.
-- Виконати в Supabase SQL Editor.
begin;

-- 1. Колонки для фото (без них міні-аппа не збереже продукт/страву з фото)
alter table public.products add column if not exists image_url text;
alter table public.dishes   add column if not exists image_url text;

-- 2. Bucket для фото
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 26214400, array['image/*','image/jpeg','image/png','image/webp','image/gif','image/jpg'])
on conflict (id) do update set
  public = true,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- 3. Чистимо старі політики storage
do $$
declare r record;
begin
  for r in select policyname from pg_policies where schemaname='storage' and tablename='objects' loop
    execute format('drop policy if exists %I on storage.objects', r.policyname);
  end loop;
end $$;

-- 4. Політики: читання + завантаження + видалення для photos
create policy "all_for_photos" on storage.objects for all to anon using (bucket_id = 'photos') with check (bucket_id = 'photos');
create policy "all_for_photos_auth" on storage.objects for all to authenticated using (bucket_id = 'photos') with check (bucket_id = 'photos');

commit;

-- Перевірка:
select id, name, public, file_size_limit, allowed_mime_types from storage.buckets where id='photos';
select column_name from information_schema.columns where table_name in ('products','dishes') and column_name='image_url';
