-- Перевірка та створення політик
alter table storage.objects enable row level security;

-- Видалити всі старі
drop policy if exists "Allow public read" on storage.objects;
drop policy if exists "Allow anon insert" on storage.objects;
drop policy if exists "Allow anon update" on storage.objects;
drop policy if exists "Allow anon delete" on storage.objects;
drop policy if exists "Public Access" on storage.objects;
drop policy if exists "public read" on storage.objects;
drop policy if exists "insert anon" on storage.objects;

create policy "public_read_photos" on storage.objects for select using (bucket_id = 'photos');
create policy "insert_photos_anon" on storage.objects for insert to anon with check (bucket_id = 'photos');
create policy "update_photos_anon" on storage.objects for update to anon using (bucket_id = 'photos');
create policy "delete_photos_anon" on storage.objects for delete to anon using (bucket_id = 'photos');
