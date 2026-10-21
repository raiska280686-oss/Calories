-- Міграція: колонки image_url для продуктів і страв.
-- Без них INSERT/PATCH із photo дає помилку:
--   PGRST204 Could not find the 'image_url' column of 'products' in the schema cache
-- Виконати в Supabase SQL Editor (один раз).

alter table public.products add column if not exists image_url text;
alter table public.dishes   add column if not exists image_url text;

-- Перевірка (має повернути 2 рядки)
select table_name, column_name
from information_schema.columns
where table_schema='public' and table_name in ('products','dishes') and column_name='image_url';
