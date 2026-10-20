-- Виконати цей SQL у Supabase SQL Editor
insert into storage.buckets (id, name, public) values ('photos', 'photos', true) on conflict (id) do update set public = true;

-- Видалити старі політики
drop policy if exists "Public read photos" on storage.objects;
drop policy if exists "Anon upload photos" on storage.objects;
drop policy if exists "Anon update photos" on storage.objects;
drop policy if exists "Anon delete photos" on storage.objects;
drop policy if exists "photos_public_read" on storage.objects;
drop policy if exists "photos_anon_insert" on storage.objects;
drop policy if exists "photos_anon_update" on storage.objects;
drop policy if exists "photos_anon_delete" on storage.objects;
drop policy if exists "public_read_photos" on storage.objects;
drop policy if exists "insert_photos_anon" on storage.objects;
drop policy if exists "update_photos_anon" on storage.objects;
drop policy if exists "delete_photos_anon" on storage.objects;
drop policy if exists "storage_read_public" on storage.objects;
drop policy if exists "storage_insert_anon" on storage.objects;
drop policy if exists "storage_update_anon" on storage.objects;
drop policy if exists "storage_delete_anon" on storage.objects;

-- Створити політики
create policy "photos_select" on storage.objects for select using (bucket_id = 'photos');
create policy "photos_insert" on storage.objects for insert with check (bucket_id = 'photos');
create policy "photos_update" on storage.objects for update using (bucket_id = 'photos');
create policy "photos_delete" on storage.objects for delete using (bucket_id = 'photos');
