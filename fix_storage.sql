begin;
alter table storage.objects enable row level security;
do $$
declare pol record;
begin
  for pol in select policyname from pg_policies where schemaname='storage' and tablename='objects' loop
    execute format('drop policy if exists %I on storage.objects', pol.policyname);
  end loop;
end $$;
create policy "allow_all_photos" on storage.objects for all using (bucket_id = 'photos') with check (bucket_id = 'photos');
commit;
