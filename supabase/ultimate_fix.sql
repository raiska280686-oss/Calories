begin;
alter table storage.objects enable row level security;
do $$
declare r record;
begin
  for r in select policyname from pg_policies where schemaname='storage' and tablename='objects' loop
    execute format('drop policy if exists %I on storage.objects', r.policyname);
  end loop;
end $$;
create policy "anon_all_photos" on storage.objects for all to anon using (bucket_id = 'photos') with check (bucket_id = 'photos');
create policy "auth_all_photos" on storage.objects for all to authenticated using (bucket_id = 'photos') with check (bucket_id = 'photos');
commit;
