// Run locally only. The output contains personal data and must stay outside the repository.
import {DatabaseSync} from 'node:sqlite';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,relative,isAbsolute} from 'node:path';
import {createHash} from 'node:crypto';
const [mode,input,output]=process.argv.slice(2);
if(!['--sqlite','--json'].includes(mode)||!input||!output)throw Error('Usage: node scripts/prepare-import.mjs --sqlite|--json INPUT PRIVATE_OUTPUT.sql');
const location=relative(resolve('.'),resolve(output));
if(!location.startsWith('..')&&!isAbsolute(location))throw Error('Save private SQL outside the repository');
const schema={employee:['id','name','city','active'],season:['year','status','is_test'],participation:['year','employee','code_hash','used'],ballot:['id','year','candidate'],archive_batch:['id','label'],archive_name:['batch','raw','n','employee']};
let data;
if(mode==='--sqlite'){
 const db=new DatabaseSync(resolve(input),{readOnly:true});
 if(db.prepare('pragma integrity_check').get().integrity_check!=='ok'||db.prepare('pragma foreign_key_check').all().length)throw Error('Invalid SQLite backup');
 data=Object.fromEntries(Object.keys(schema).map(t=>[t,db.prepare('select * from '+t).all()]));db.close();
}else{
 data=JSON.parse(await readFile(input,'utf8'));
 if(data.format!=='people-year-postgres-v1')throw Error('Unsupported backup');
 if(Array.isArray(data.season_restart))schema.season_restart=['id','year','created_at','snapshot'];
}
const quote=v=>v===null?'null':"'"+String(v).replaceAll("'","''")+"'";
const statements=['begin;','select pg_advisory_xact_lock(731682026);',"do $$ begin if exists(select 1 from people.employee) or exists(select 1 from people.season) then raise exception 'Target is not empty'; end if; end $$;"];
for(const [t,cols] of Object.entries(schema)){
 if(!Array.isArray(data[t])||data[t].some(r=>cols.some(c=>r[c]===undefined)))throw Error('Invalid table '+t);
 if(data[t].length)statements.push('insert into people.'+t+'('+cols.join(',')+') values '+data[t].map(r=>'('+cols.map(c=>quote(typeof r[c]==='object'&&r[c]!==null?JSON.stringify(r[c]):r[c])).join(',')+')').join(',')+';');
 console.log(t+': '+data[t].length+' rows');
}
statements.push('commit;');
await writeFile(output,statements.join('\n'),{mode:0o600,flag:'wx'});
console.log('Private import prepared; source backup unchanged. Apply via a trusted management connection.');
