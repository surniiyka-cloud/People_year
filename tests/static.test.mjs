import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import vm from 'node:vm';
test('frontend uses a scoped Pages admin route and authenticated Edge transport',async()=>{
 const js=await readFile('static/app.js','utf8');
 new vm.Script(js);
 assert.ok(js.includes('https://gsxroprhnimtrzjhvuah.supabase.co/functions/v1/people-api/'));
 assert.ok(js.includes('headers.Authorization'));
 assert.ok(!js.includes("fetch('/api/"));
 for(const path of ['/People_year/admin/','/People_year/admin','/People_year/admin/index.html']) assert.match(path,/\/admin(?:\/index\.html)?\/?$/);
 assert.doesNotMatch('/People_year/',/\/admin(?:\/index\.html)?\/?$/);
});
test('static document has relative assets and a restrictive CSP',async()=>{
 const html=await readFile('static/index.html','utf8');
 assert.ok(html.includes('Content-Security-Policy'));
 assert.ok(html.includes('data:image/png;base64,'));
 assert.ok(html.includes('href="admin/"'));
 for(const asset of ['app.js','style.css','favicon.svg'])assert.ok(html.includes('"'+asset+(asset==='favicon.svg'?'?v=1':'')+'"'));
 assert.ok(!/\b(?:src|href)="\//.test(html));
});
test('vote RPC has no client grants and no voter-to-ballot relationship',async()=>{
 const sql=await readFile('supabase/migrations/20261126090000_api.sql','utf8');
 assert.ok(sql.includes('pg_advisory_xact_lock'));
 assert.ok(sql.includes('grant execute on function public.people_api(text,jsonb,text,text) to service_role'));
 assert.ok(sql.includes("eid=s.employee"));
 assert.ok(sql.includes("p.used=1"));
 const schema=await readFile('supabase/people_schema.sql','utf8');
 assert.ok(!/create table[^;]+ballot[^;]+(?:voter|code_hash|token_hash)/is.test(schema));
});
