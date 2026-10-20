-- Увімкнути RLS якщо вимкнено (зазвичай увімкнено)
-- Політики для storage.objects
drop policy if exists "Public read photos" on storage.objects;
drop policy if exists "Anon upload photos" on storage.objects;
drop policy if exists "Anon update photos" on storage.objects;
drop policy if exists "Anon delete photos" on storage.objects;
drop policy if exists "photos_public_read" on storage.objects;
drop policy if exists "photos_anon_insert" on storage.objects;
drop policy if exists "photos_anon_update" on storage.objects;
drop policy if exists "photos_anon_delete" on storage.objects;

create policy "Public read photos" on storage.objects
  for select
  using (bucket_id = 'photos');

create policy "Anon upload photos" on storage.objects
  for insert to anon
  with check (bucket_id = 'photos');

create policy "Anon update photos" on storage.objects
  for update to anon
  using (bucket_id = 'photos')
  with check (bucket_id = 'photos');

create policy "Anon delete photos" on storage.objects
  for delete to anon
  using (bucket_id = 'photos');
