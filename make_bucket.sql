insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) 
values ('photos', 'photos', true, 5242880, array['image/jpeg','image/png','image/webp','image/gif','image/jpg'])
on conflict (id) do update set public = true, file_size_limit = 5242880;
