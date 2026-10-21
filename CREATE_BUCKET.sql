-- Створи bucket через SQL Editor (Storage API може вимагати політики)
insert into storage.buckets (id, name, public)
values ('photos', 'photos', true)
on conflict (id) do update set public = true;
