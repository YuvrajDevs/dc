-- The daily mart must account for every authorization exactly once.
select 1
from (select count(*) as n from {{ ref('fct_authorization') }}) a,
     (select sum(attempts) as n from {{ ref('mart_auth_daily') }}) m
where a.n <> m.n
