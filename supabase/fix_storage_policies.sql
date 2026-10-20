-- Виконати в SQL Editor
begin;

-- Увімкнути RLS
alter table storage.objects enable row level security;

-- Очистити політики
do $$
declare
  pol record;
begin
  for pol in select policyname from pg_policies where schemaname='storage' and tablename='objects'
  loop
    execute format('drop policy if exists %I on storage.objects', pol.policyname);
  end loop;
end $$;

-- Створити нові
create policy "storage_read_public" on storage.objects for select using (bucket_id = 'photos');
create policy "storage_insert_anon" on storage.objects for insert to anon with check (bucket_id = 'photos');
create policy "storage_update_anon" on storage.objects for update to anon using (bucket_id = 'photos') with check (bucket_id = 'photos');
create policy "storage_delete_anon" on storage.objects for delete to anon using (bucket_id = 'photos');

commit;
