-- The answer key must never be loaded where the pipeline can see it.
select table_schema, table_name
from information_schema.tables
where table_name ilike '%answer_key%' or table_name ilike '%expected_link%'
