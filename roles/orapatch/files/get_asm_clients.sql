set head off
set feedback off
set pagesize 100
set linesize 100
set timi off
select ';'||asm_clients.col
from dual,(select count(*) cnt, listagg(db_name||','||instance_name,';') within group (order by instance_name) col from (select distinct db_name, instance_name from v$asm_client where db_name not like '+%' and db_name not like '\_%' escape '\')) asm_clients
where asm_clients.cnt > 0;
exit
