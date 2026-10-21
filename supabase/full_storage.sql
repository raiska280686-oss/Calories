begin;
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 26214400, array['image/*','image/jpeg','image/png','image/webp','image/gif','image/jpg'])
on conflict (id) do update set public = true;

do $$
declare r record;
begin
  for r in select policyname from pg_policies where schemaname='storage' and tablename='objects' loop
    execute format('drop policy if exists %I on storage.objects', r.policyname);
  end loop;
end $$;

create policy "all_for_photos" on storage.objects for all to anon using (bucket_id = 'photos') with check (bucket_id = 'photos');
create policy "all_for_photos_auth" on storage.objects for all to authenticated using (bucket_id = 'photos') with check (bucket_id = 'photos');
commit;
