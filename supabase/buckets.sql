insert into storage.buckets (id, name, public) values ('photos', 'photos', true) on conflict (id) do nothing;
update storage.buckets set public = true where id = 'photos';
