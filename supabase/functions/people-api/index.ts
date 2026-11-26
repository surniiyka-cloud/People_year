import ExcelJS from 'npm:exceljs@4.4.0';
import { unzipSync } from 'npm:fflate@0.8.2';

const ORIGINS = new Set(['https://surniiyka-cloud.github.io', 'http://localhost:8085', 'http://127.0.0.1:8085']);
const URL_BASE = Deno.env.get('SUPABASE_URL')!;
const SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const routes = new Set(['state','login','admin-login','logout','search','vote','new-season','dashboard','employee-save','employee-toggle','import','codes','status','archive','archive-import','archive-match','backup','export','reset-codes','reset-test']);
const hash = async (v: string) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(v)))).map(x=>x.toString(16).padStart(2,'0')).join('');
const randomToken = () => Array.from(crypto.getRandomValues(new Uint8Array(32))).map(x=>x.toString(16).padStart(2,'0')).join('');
const b64 = (bytes: Uint8Array) => { let s=''; for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(s); };
function value(cell: ExcelJS.Cell): string {
  const v=cell.value;
  if(v===null || v===undefined)return '';
  if(typeof v==='object') {
    if('formula' in v || 'sharedFormula' in v)return String((v as {result?:unknown}).result??'').trim();
    if('richText' in v)return v.richText.map(x=>x.text).join('').trim();
    if('text' in v)return String(v.text).trim();
    return '';
  }
  return String(v).trim();
}
async function workbook(encoded: unknown) {
  if(typeof encoded!=='string'||encoded.length>8_000_000)throw Error('Недопустимый размер Excel');
  let bytes: Uint8Array<ArrayBuffer>; try{bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));}catch{throw Error('Некорректный файл');}
  // Inspect ZIP headers before inflation: reject oversized or suspicious archives.
  let total=0, entries=0;
  unzipSync(bytes,{filter(entry){total+=entry.originalSize; entries++; if(total>24_000_000||entries>1000)throw Error('Excel слишком большой'); return false;}});
  const wb = new ExcelJS.Workbook(); await wb.xlsx.load(bytes.buffer);
  if(wb.worksheets.some(s=>s.rowCount>10000||s.columnCount>100))throw Error('Excel слишком большой');
  return {wb,bytes};
}
async function rpc(action:string,payload:Record<string,unknown>,tokenHash:string,ipHash:string) {
 const response = await fetch(URL_BASE+'/rest/v1/rpc/people_api', {method:'POST',headers:{'Content-Type':'application/json',apikey:SERVICE_KEY,Authorization:'Bearer '+SERVICE_KEY},body:JSON.stringify({action,payload,token_hash:tokenHash,ip_hash:ipHash})});
 if(!response.ok)throw Error('Сервис временно недоступен');
 return await response.json();
}
Deno.serve(async req => {
 const origin=req.headers.get('origin')||'';
 const headers:Record<string,string>={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Vary':'Origin','Access-Control-Allow-Headers':'content-type, authorization, apikey','Access-Control-Allow-Methods':'GET, POST, OPTIONS'};
 if(ORIGINS.has(origin))headers['Access-Control-Allow-Origin']=origin;
 const send=(obj:unknown,status=200)=>new Response(JSON.stringify(obj),{status,headers});
 if(origin&&!ORIGINS.has(origin))return send({error:'Нет доступа'},403);
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers});
 const action=new URL(req.url).pathname.split('/').filter(Boolean).at(-1)!;
 if(!routes.has(action))return send({error:'Нет маршрута'},404);
 if(req.method!=='POST'&&!(action==='state'&&req.method==='GET'))return send({error:'Метод не поддерживается'},405);
 try {
  let payload:Record<string,unknown>={};
  if(req.method==='POST'){
   if(!req.headers.get('content-type')?.startsWith('application/json'))return send({error:'Неверный формат запроса'},415);
   if(Number(req.headers.get('content-length')||0)>9_000_000)return send({error:'Недопустимый размер запроса'},413);
   const reader=req.body!.getReader(); let size=0; const chunks:Uint8Array[]=[];
   while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>9_000_000){await reader.cancel();return send({error:'Недопустимый размер запроса'},413);}chunks.push(value);}
   const all=new Uint8Array(size);let offset=0;for(const c of chunks){all.set(c,offset);offset+=c.length;}
   payload=JSON.parse(new TextDecoder().decode(all));
   if(!payload||typeof payload!=='object'||Array.isArray(payload))throw Error('Некорректный запрос');
  }
  const login=action==='login'||action==='admin-login';
  const token=login?randomToken():(req.headers.get('authorization')?.replace(/^Bearer /,'')||'');
  const tokenHash=await hash(token);
  const ipHash=await hash(req.headers.get('x-forwarded-for')?.split(',')[0]?.trim()||'unknown');
  if(action==='import'||action==='archive-import'){
   // Authenticate before decoding an expensive/untrusted workbook.
   const session=await rpc('state',{},tokenHash,ipHash);
   if(session.role!=='admin')return send({error:'Войдите в систему'},401);
   const {wb,bytes}=await workbook(payload.file);
   delete payload.file;
   if(action==='import'){
    let city='';const employees: {id:string;name:string;city:string}[]=[];const seen=new Set<string>();
    for(const sheet of wb.worksheets)sheet.eachRow(row=>{
     const a=value(row.getCell(1)),name=value(row.getCell(2)),id=value(row.getCell(6));
     if(a&&!name&&!/^\d+$/.test(a)&&!['Подразделение','№'].includes(a)){city=a;return;}
     if(!/^\d+$/.test(a)||!name||!id)return;
     if(seen.has(id))throw Error('Повтор табельного номера: '+id);
     seen.add(id);employees.push({id,name,city});
    });
    if(!employees.length)throw Error('Не найдено сотрудников. Ожидается исходный формат: №, сотрудник, табельный номер в столбце F.');
    payload.employees=employees;
   }else{
    const sheet=wb.worksheets[0];
    if(!sheet||![2,3,4].every(i=>value(sheet.getRow(1).getCell(i)).toLowerCase().includes('сотрудника')))throw Error('Ожидается архив Google Forms с тремя колонками кандидатов');
    const counts=new Map<string,number>();sheet.eachRow((row,i)=>{if(i===1)return;for(const col of [2,3,4]){const raw=value(row.getCell(col));if(raw)counts.set(raw,(counts.get(raw)||0)+1);}});
    if(!counts.size)throw Error('Нет ответов');
    payload.batch=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
    payload.names=[...counts].map(([raw,n])=>({raw,n}));
   }
  }
  const result=await rpc(action,payload,tokenHash,ipHash);
  const status=result.http_status||(result.error?400:200);delete result.http_status;
  if(login&&result.ok)result.token=token;
  if((action==='codes'||action==='export')&&!result.error){
   const wb=new ExcelJS.Workbook(),sheet=wb.addWorksheet(result.sheet||'Отчёт');
   sheet.addRow(result.header); for(const row of result.rows)sheet.addRow(row.map((v:unknown)=>typeof v==='string'&&/^[=+\-@]/.test(v)?"'"+v:v));
   sheet.columns.forEach((col,i)=>col.width=i===0?42:32);
   result.file=b64(new Uint8Array(await wb.xlsx.writeBuffer()));delete result.header;delete result.sheet;
   if(action==='export')delete result.rows;
  }
  if(action==='backup'&&result.backup){result.file=b64(new TextEncoder().encode(JSON.stringify(result.backup)));delete result.backup;}
  return send(result,status);
 }catch(e){return send({error:e instanceof SyntaxError?'Некорректный запрос':e instanceof Error?e.message:'Операция не выполнена'},400);}
});
