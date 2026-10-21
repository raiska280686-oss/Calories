begin;
-- створити bucket
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 52428800, array['image/*','image/jpeg','image/png','image/webp','image/gif'])
on conflict (id) do update set public = true;

-- прибрати старі
do $$
declare r record;
begin
  for r in select policyname from pg_policies where schemaname='storage' and tablename='objects' loop
    execute format('drop policy if exists %I on storage.objects', r.policyname);
  end loop;
end $$;

-- дозволити всім
create policy "photos_all" on storage.objects for all using (bucket_id = 'photos') with check (bucket_id = 'photos');
commit;
