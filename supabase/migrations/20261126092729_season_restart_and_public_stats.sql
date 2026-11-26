-- Private recovery snapshots are created atomically before an administrator restarts a season.
create table if not exists people.season_restart (
 id uuid primary key default gen_random_uuid(),
 year integer not null references people.season(year),
 created_at timestamptz not null default now(),
 snapshot jsonb not null
);
alter table people.season_restart enable row level security;
revoke all on people.season_restart from public,anon,authenticated;
create or replace function public.people_api(action text, payload jsonb, token_hash text, ip_hash text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 s people.session%rowtype; p record; st people.season%rowtype; y integer;
 result jsonb; a jsonb; item jsonb; r record; code text; eid text; n integer; k text; lim integer;
begin
 -- Serialize state transitions, code revocations and votes. Each call is one transaction.
 perform pg_advisory_xact_lock(731682026);
 delete from people.session where expires < now();
 if action in ('login','admin-login') then
   delete from people.rate_limit where started < now()-interval '5 minutes';
   foreach k in array array['ip:'||ip_hash,'global'] loop
     lim:=case when k='global' then 180 else 12 end;
     insert into people.rate_limit(key,started,attempts) values(k,now(),1)
       on conflict(key) do update set attempts=people.rate_limit.attempts+1 returning attempts into n;
     if n>lim then return jsonb_build_object('error','Слишком много попыток. Повторите через 5 минут.','http_status',429); end if;
   end loop;
 end if;
 -- Catch validation errors inside the rate-limit transaction so failed logins still count.
 begin
 if action='login' then
   select x.* into p from people.participation x join people.season z using(year) join people.employee e on e.id=x.employee
     where x.code_hash=encode(sha256(convert_to(upper(trim(payload->>'code')),'UTF8')),'hex') and z.status='open' and e.active=1;
   if not found then raise exception 'Код недействителен или голосование закрыто'; end if;
   insert into people.session values(token_hash,'voter',p.year,p.employee,p.code_hash,now()+interval '1 hour');
   return '{"ok":true}'::jsonb;
 elsif action='admin-login' then
   if not exists(select 1 from people.admin_credential where id=1 and password_hash=extensions.crypt(left(payload->>'password',200),password_hash)) then raise exception 'Неверный пароль'; end if;
   insert into people.session(token_hash,role,expires) values(token_hash,'admin',now()+interval '1 hour');
   return '{"ok":true}'::jsonb;
 end if;
 if action='public-stats' then
   select * into st from people.season where is_test=0 order by (status='open') desc,year desc limit 1;
   if not found then return jsonb_build_object('year',null,'eligible',0,'voted',0,'pending',0,'turnout',0,'status','draft'); end if;
   select count(*),count(*) filter(where coalesce(x.used,0)=1) into n,lim
     from people.employee e left join people.participation x on x.employee=e.id and x.year=st.year where e.active=1 or x.used=1;
   return jsonb_build_object('year',st.year,'eligible',n,'voted',lim,'pending',n-lim,'turnout',case when n=0 then 0 else round(lim*100.0/n)::integer end,'status',st.status);
 end if;
 select * into s from people.session x where x.token_hash=people_api.token_hash and expires>now();
 if action='logout' then delete from people.session x where x.token_hash=people_api.token_hash; return '{"ok":true}'::jsonb; end if;
 if s.role is null then
   if action='state' then return '{"role":null}'::jsonb; end if;
   return '{"error":"Войдите в систему","http_status":401}'::jsonb;
 end if;
 if s.role='voter' then
   select x.used,z.status,z.is_test,e.active into p from people.participation x join people.season z using(year) join people.employee e on e.id=x.employee
     where x.year=s.year and x.employee=s.employee and x.code_hash=s.code_hash;
   if not found or p.active<>1 then
     delete from people.session x where x.token_hash=people_api.token_hash;
     if action='state' then return '{"role":null}'::jsonb; end if;
     return '{"error":"Доступ отозван","http_status":403}'::jsonb;
   end if;
   if action='state' then return jsonb_build_object('role','voter','year',s.year,'used',p.used=1,'status',p.status,'is_test',p.is_test=1); end if;
   if action='search' then
     if p.used=1 or p.status<>'open' then raise exception 'Голосование недоступно'; end if;
     select coalesce(jsonb_agg(to_jsonb(q)),'[]') into a from
       (select e.id,e.name,e.city from people.employee e where active=1 and id<>s.employee and people.norm(left(payload->>'q',100))<>''
       and not exists(select 1 from unnest(string_to_array(people.norm(left(payload->>'q',100)),' ')) t
         where not exists(select 1 from unnest(string_to_array(people.norm(e.name||' '||e.city),' ')) w where starts_with(w,t))) order by e.name limit 12) q;
     return jsonb_build_object('employees',a);
   elsif action='vote' then
     eid:=payload->>'candidate';
     if eid=s.employee then raise exception 'За себя голосовать нельзя'; end if;
     if not exists(select 1 from people.employee where id=eid and active=1) then raise exception 'Кандидат недоступен'; end if;
     if p.status<>'open' or p.used=1 then raise exception 'Голос уже учтён или доступ закрыт'; end if;
     update people.participation set used=1 where year=s.year and employee=s.employee and code_hash=s.code_hash and used=0;
     if not found then raise exception 'Голос уже учтён или доступ закрыт'; end if;
     insert into people.ballot values(encode(extensions.gen_random_bytes(24),'hex'),s.year,eid);
     return '{"ok":true}'::jsonb;
   end if;
   return '{"error":"Нет доступа","http_status":403}'::jsonb;
 end if;
 if action='state' then return jsonb_build_object('role','admin','seasons',(select coalesce(jsonb_agg(to_jsonb(z) order by year desc),'[]') from people.season z)); end if;
 y:=coalesce((payload->>'year')::integer,2026);
 if action='new-season' then
   if y<2026 or y>2100 or (y=2026 and coalesce((payload->>'is_test')::boolean,false)) then raise exception 'Неверный год'; end if;
   insert into people.season(year,is_test) values(y,case when (payload->>'is_test')::boolean then 1 else 0 end);
   return '{"ok":true}'::jsonb;
 end if;
 select * into st from people.season where year=y;
 if not found then raise exception 'Сезон не найден'; end if;
 if action='dashboard' then
   select coalesce(jsonb_agg(to_jsonb(q) order by name),'[]') into a from
    (select e.*,coalesce(x.used,0) used,case when x.code_hash is null then 0 else 1 end issued from people.employee e left join people.participation x on e.id=x.employee and x.year=y) q;
   result:=jsonb_build_object('employees',a,'status',st.status,'is_test',st.is_test=1,'ranking','[]'::jsonb);
   if st.status='closed' then
    select coalesce(jsonb_agg(to_jsonb(q)),'[]') into a from (select e.name,e.city,count(*) votes from people.ballot b join people.employee e on e.id=b.candidate where b.year=y group by e.id order by votes desc,e.name) q;
    result:=jsonb_set(result,'{ranking}',a);
   end if;
   return result;
 elsif action in ('employee-save','employee-toggle','import') then
   if exists(select 1 from people.season where status='open') then raise exception 'Изменение справочника доступно только вне открытого голосования'; end if;
   if action='import' then
     if jsonb_array_length(payload->'employees')=0 then raise exception 'Не найдено сотрудников'; end if;
     for item in select * from jsonb_array_elements(payload->'employees') loop
       if trim(item->>'id')='' or trim(item->>'name')='' then raise exception 'Некорректные данные'; end if;
       insert into people.employee(id,name,city) values(item->>'id',item->>'name',item->>'city') on conflict(id) do update set name=excluded.name,city=excluded.city,active=1;
     end loop;
     return jsonb_build_object('count',jsonb_array_length(payload->'employees'));
   end if;
   eid:=trim(payload->>'id');
   if coalesce(eid,'')='' then raise exception 'Введите табельный номер'; end if;
   if action='employee-toggle' then
     update people.employee set active=case when (payload->>'active')::boolean then 1 else 0 end where id=eid;
   else
     if coalesce(trim(payload->>'name'),'')='' or coalesce(trim(payload->>'city'),'')='' then raise exception 'Заполните ФИО и подразделение'; end if;
     if coalesce((payload->>'edit')::boolean,false) then update people.employee set name=trim(payload->>'name'),city=trim(payload->>'city') where id=eid;
     else insert into people.employee(id,name,city) values(eid,trim(payload->>'name'),trim(payload->>'city')); end if;
   end if;
   if not found then raise exception 'Сотрудник не найден'; end if;
 elsif action='reset-codes' then
   if payload->>'confirm' is distinct from y::text then raise exception 'Подтвердите номер сезона'; end if;
   update people.participation set code_hash=null where year=y and code_hash is not null; get diagnostics n=row_count;
   return jsonb_build_object('ok',true,'revoked',n);
 elsif action='restart-season' then
   if payload->>'confirm' is distinct from ('ПЕРЕЗАПУСК '||y::text) then raise exception 'Для подтверждения введите ПЕРЕЗАПУСК и год сезона'; end if;
   insert into people.season_restart(year,snapshot) values(y,jsonb_build_object(
     'season',to_jsonb(st),
     'participation',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.participation t where t.year=y),
     'ballot',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.ballot t where t.year=y))) returning id::text into eid;
   delete from people.session x where x.role='voter' and x.year=y;
   delete from people.ballot where year=y;
   delete from people.participation where year=y;
   update people.season set status='draft' where year=y;
   return jsonb_build_object('ok',true,'backup_id',eid);
 elsif action='reset-test' then
   if st.is_test<>1 or y=2026 then raise exception 'Сброс разрешён только тестовым сезонам'; end if;
   if st.status='open' then raise exception 'Сначала закройте тестовое голосование'; end if;
   if payload->>'confirm' is distinct from y::text then raise exception 'Подтвердите номер сезона'; end if;
   delete from people.ballot where year=y; delete from people.participation where year=y; update people.season set status='draft' where year=y;
 elsif action='codes' then
   if st.status='closed' then raise exception 'Сезон завершён'; end if;
   a:='[]';
   for r in select e.id,e.name,e.city from people.employee e left join people.participation x on x.employee=e.id and x.year=y
     where e.active=1 and coalesce(x.used,0)=0 and (coalesce(payload->>'city','')='' or e.city=payload->>'city') and (coalesce(payload->>'employee','')='' or e.id=payload->>'employee')
     and (x.code_hash is null or coalesce((payload->>'replace')::boolean,false)) order by e.name loop
     code:=upper(encode(extensions.gen_random_bytes(3),'hex')||'-'||encode(extensions.gen_random_bytes(3),'hex')||'-'||encode(extensions.gen_random_bytes(3),'hex'));
     insert into people.participation(year,employee,code_hash) values(y,r.id,encode(sha256(convert_to(code,'UTF8')),'hex'))
       on conflict(year,employee) do update set code_hash=excluded.code_hash where people.participation.used=0;
     a:=a||jsonb_build_array(jsonb_build_array(r.name,r.city,code));
   end loop;
   return jsonb_build_object('rows',a,'sheet','Коды','header',jsonb_build_array('Сотрудник','Подразделение','Код'));
 elsif action='status' then
   if not ((st.status='draft' and payload->>'status'='open') or (st.status='open' and payload->>'status'='closed')) then raise exception 'Недопустимый переход'; end if;
   if payload->>'status'='open' and not exists(select 1 from people.participation x join people.employee e on e.id=x.employee where x.year=y and x.code_hash is not null and e.active=1) then raise exception 'Сначала выдайте коды'; end if;
   update people.season set status=payload->>'status' where year=y;
 elsif action='archive' then
   return jsonb_build_object('batches',(select coalesce(jsonb_agg(to_jsonb(b) order by b.label),'[]') from people.archive_batch b),'names',(select coalesce(jsonb_agg(to_jsonb(b) order by b.n desc,b.raw),'[]') from people.archive_name b));
 elsif action='archive-import' then
   insert into people.archive_batch values(payload->>'batch',left(coalesce(payload->>'label','Архив'),150));
   for item in select * from jsonb_array_elements(payload->'names') loop
     select case when count(*)=1 then min(id) else null end into eid from people.employee e
       where (select array_agg(t order by t) from unnest(string_to_array(people.norm(e.name),' ')) t)=(select array_agg(t order by t) from unnest(string_to_array(people.norm(item->>'raw'),' ')) t);
     insert into people.archive_name values(payload->>'batch',item->>'raw',(item->>'n')::integer,eid);
   end loop;
 elsif action='archive-match' then
   eid:=nullif(payload->>'employee','');
   update people.archive_name set employee=eid where batch=payload->>'batch' and raw=payload->>'raw';
   if not found then raise exception 'Запись не найдена'; end if;
 elsif action='export' then
   if payload->>'kind'='pending' then
     select coalesce(jsonb_agg(jsonb_build_array(q.name,q.city)),'[]') into a from (select e.name,e.city from people.employee e left join people.participation x on x.employee=e.id and x.year=y where active=1 and coalesce(x.used,0)=0 and (coalesce(payload->>'city','')='' or e.city=payload->>'city') order by e.city,e.name) q;
     return jsonb_build_object('rows',a,'header',jsonb_build_array('Сотрудник','Подразделение'));
   elsif payload->>'kind'='ranking' and st.status='closed' then
     select coalesce(jsonb_agg(jsonb_build_array(q.name,q.city,q.votes)),'[]') into a from (select e.name,e.city,count(*) votes from people.ballot b join people.employee e on e.id=b.candidate where b.year=y group by e.id order by votes desc,e.name) q;
     return jsonb_build_object('rows',a,'header',jsonb_build_array('Сотрудник','Подразделение','Голоса'));
   end if;
   raise exception 'Отчёт недоступен';
 elsif action='backup' then
   return jsonb_build_object('backup',jsonb_build_object('format','people-year-postgres-v1','season_restart',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.season_restart t),'employee',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.employee t),'season',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.season t),'participation',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.participation t),'ballot',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.ballot t),'archive_batch',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.archive_batch t),'archive_name',(select coalesce(jsonb_agg(to_jsonb(t)),'[]') from people.archive_name t)));
 else return '{"error":"Нет маршрута","http_status":404}'::jsonb;
 end if;
 return '{"ok":true}'::jsonb;
 exception when raise_exception then return jsonb_build_object('error',sqlerrm,'http_status',400);
 when others then return '{"error":"Операция не выполнена. Проверьте данные.","http_status":400}'::jsonb;
 end;
end $$;
revoke all on function public.people_api(text,jsonb,text,text) from public,anon,authenticated;
grant execute on function public.people_api(text,jsonb,text,text) to service_role;
revoke all on function people.norm(text) from public,anon,authenticated;
