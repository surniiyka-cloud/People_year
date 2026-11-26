import os, sqlite3, secrets, hashlib, hmac, json, time, re, io, base64, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from contextlib import contextmanager
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from openpyxl import load_workbook, Workbook
ROOT=Path(__file__).parent
DB=os.getenv('PEOPLE_DB',str(ROOT/'data'/'people.sqlite3'))
ADMIN=os.getenv('ADMIN_PASSWORD','')
SECURE=os.getenv('SECURE_COOKIE','1')=='1'
SESS={}; LIMIT={}; LOCK=threading.Lock()
@contextmanager
def connect():
    c=sqlite3.connect(DB,timeout=15,isolation_level=None);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    try: yield c
    finally: c.close()
def init():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS employee(id TEXT PRIMARY KEY,name TEXT NOT NULL,city TEXT NOT NULL,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS season(year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','open','closed')));
CREATE TABLE IF NOT EXISTS participation(year INTEGER REFERENCES season,employee TEXT REFERENCES employee,code_hash TEXT UNIQUE,used INTEGER DEFAULT 0,PRIMARY KEY(year,employee));
CREATE TABLE IF NOT EXISTS ballot(id TEXT PRIMARY KEY,year INTEGER REFERENCES season,candidate TEXT REFERENCES employee);
INSERT OR IGNORE INTO season(year) VALUES(2026);''')
        if not any(r['name']=='is_test' for r in c.execute('PRAGMA table_info(season)')):
            c.execute('ALTER TABLE season ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0')
        c.execute("CREATE TABLE IF NOT EXISTS archive_batch(id TEXT PRIMARY KEY,label TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS archive_name(batch TEXT REFERENCES archive_batch(id),raw TEXT NOT NULL,n INTEGER NOT NULL,employee TEXT REFERENCES employee(id),PRIMARY KEY(batch,raw))")
def digest(code): return hashlib.sha256(code.encode()).hexdigest()
def norm(s):return re.sub(r'[^а-яa-z0-9]+',' ',s.lower().replace('ё','е')).strip()
def matches(s,q):return all(any(w.startswith(t) for w in norm(s).split()) for t in norm(q).split())
def makecode(): return '-'.join(secrets.token_hex(3).upper() for _ in range(3))
def rows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args)]
def import_employees(raw):
    w=load_workbook(io.BytesIO(raw),read_only=True,data_only=True); out=[]; city=''; seen=set()
    for sheet in w:
        for r in sheet.values:
            a=str(r[0] or '').strip() if r else ''; name=str(r[1] or '').strip() if len(r)>1 else ''; num=str(r[5] or '').strip() if len(r)>5 else ''
            if a and not name and not a.isdigit() and a not in ('Подразделение','№'): city=a;continue
            if not a.isdigit() or not name or not num:continue
            if num in seen:raise ValueError('Повтор табельного номера: '+num)
            seen.add(num);out.append((num,name,city))
    if not out:raise ValueError('Не найдено сотрудников. Ожидается исходный формат: №, сотрудник, табельный номер в столбце F.')
    return out
class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass # no request or ballot logs
    def send(self,obj,status=200,cookie=None):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(b)))
        if cookie is not None:self.send_header('Set-Cookie','sid='+cookie+'; Path=/; HttpOnly; SameSite=Strict'+('; Secure' if SECURE else '')+('' if cookie else '; Max-Age=0'))
        self.end_headers();self.wfile.write(b)
    def session(self):
        cookie=SimpleCookie();cookie.load(self.headers.get('Cookie','')); sid=cookie.get('sid');sid=sid.value if sid else '';s=SESS.get(sid)
        return sid,s if s and s['expires']>time.time() else None
    def login(self,s):
        sid,_=self.session();token=secrets.token_urlsafe(32)
        with LOCK:
            SESS.pop(sid,None);SESS[token]={**s,'expires':time.time()+3600}
        self.send({'ok':True},cookie=token)
    def rate(self):
        now=time.time();ip=self.client_address[0]
        with LOCK:
            for key in list(LIMIT):
                if now-LIMIT[key][0]>300:LIMIT.pop(key,None)
            for key,maxn in [('ip:'+ip,12),('global',180)]:
                start,n=LIMIT.get(key,(now,0))
                if n>=maxn:raise ValueError('Слишком много попыток. Повторите через 5 минут.')
                LIMIT[key]=(start,n+1)
    def do_GET(self):
        self.path=urlsplit(self.path).path
        if self.path=='/admin/':self.path='/admin'
        if self.path in ('/','/admin','/style.css','/app.js'):
            p=ROOT/'static'/({'/':'index.html','/admin':'index.html','/style.css':'style.css','/app.js':'app.js'}[self.path]);b=p.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','css':'text/css','js':'text/javascript; charset=utf-8'}[p.suffix[1:]]);self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'");self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        self.api({})
    def do_POST(self):
        self.path=urlsplit(self.path).path
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Неверный формат запроса')
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=12_000_000:raise ValueError('Недопустимый размер запроса')
            self.api(json.loads(self.rfile.read(n)))
        except Exception:self.send({'error':'Некорректный запрос'},400)
    def api(self,d):
        sid,s=self.session();path=self.path
        try:
            with connect() as c:
                if path=='/api/login' and self.command=='POST':
                    self.rate();code=str(d.get('code','')).upper().strip();p=c.execute('SELECT p.year,p.employee,p.used FROM participation p JOIN season s ON s.year=p.year JOIN employee e ON e.id=p.employee WHERE p.code_hash=? AND s.status=\'open\' AND e.active=1',(digest(code),)).fetchone()
                    if not p:raise ValueError('Код недействителен или голосование закрыто')
                    return self.login({'role':'voter','year':p['year'],'employee':p['employee'],'hash':digest(code)})
                if path=='/api/admin-login' and self.command=='POST':
                    self.rate()
                    if not ADMIN or not hmac.compare_digest(str(d.get('password','')).encode(),ADMIN.encode()):raise ValueError('Неверный пароль')
                    return self.login({'role':'admin'})
                if path=='/api/logout' and self.command=='POST':SESS.pop(sid,None);return self.send({'ok':True},cookie='')
                if not s:return self.send({'role':None} if path=='/api/state' else {'error':'Войдите в систему'},200 if path=='/api/state' else 401)
                if s['role']=='voter':
                    y,e=s['year'],s['employee'];p=c.execute('SELECT p.used,s.status,s.is_test,e.active FROM participation p JOIN season s USING(year) JOIN employee e ON e.id=p.employee WHERE p.year=? AND p.employee=? AND p.code_hash=?',(y,e,s['hash'])).fetchone()
                    if not p or not p['active']:return self.send({'error':'Доступ отозван'},403)
                    if path=='/api/state':return self.send({'role':'voter','year':y,'used':bool(p['used']),'status':p['status'],'is_test':bool(p['is_test'])})
                    if path=='/api/search' and self.command=='POST':
                        if p['used'] or p['status']!='open':raise ValueError('Голосование недоступно')
                        q=str(d.get('q',''))[:100];a=rows(c,'SELECT id,name,city FROM employee WHERE active=1 AND id<>? ORDER BY name',(e,));return self.send({'employees':[{'id':r['id'],'name':r['name'],'city':r['city']} for r in a if norm(q) and matches(r['name']+' '+r['city'],q)][:12]})
                    if path=='/api/vote' and self.command=='POST':
                        target=str(d.get('candidate',''));c.execute('BEGIN IMMEDIATE')
                        if target==e:raise ValueError('За себя голосовать нельзя')
                        if not c.execute('SELECT 1 FROM employee WHERE id=? AND active=1',(target,)).fetchone():raise ValueError('Кандидат недоступен')
                        n=c.execute("UPDATE participation SET used=1 WHERE year=? AND employee=? AND code_hash=? AND used=0 AND EXISTS(SELECT 1 FROM season WHERE year=? AND status='open') AND EXISTS(SELECT 1 FROM employee WHERE id=? AND active=1)",(y,e,s['hash'],y,e)).rowcount
                        if n!=1:raise ValueError('Голос уже учтён или доступ закрыт')
                        c.execute('INSERT INTO ballot VALUES(?,?,?)',(secrets.token_hex(24),y,target));c.commit();return self.send({'ok':True})
                    return self.send({'error':'Нет доступа'},403)
                if s['role']!='admin':return self.send({'error':'Нет доступа'},403)
                if path=='/api/state':return self.send({'role':'admin','seasons':rows(c,'SELECT * FROM season ORDER BY year DESC')})
                if self.command!='POST':return self.send({'error':'Нет маршрута'},404)
                y=int(d.get('year',2026));
                if path in ('/api/new-season','/api/import','/api/codes','/api/status','/api/employee-save','/api/employee-toggle','/api/reset-test','/api/archive-import','/api/archive-match'):c.execute('BEGIN IMMEDIATE')
                status=c.execute('SELECT status,is_test FROM season WHERE year=?',(y,)).fetchone()
                if path=='/api/new-season':
                    if not 2026<=y<=2100:raise ValueError('Неверный год')
                    c.execute('INSERT INTO season(year,is_test) VALUES(?,?)',(y,int(bool(d.get('is_test')))));c.commit();return self.send({'ok':True})
                if not status:raise ValueError('Сезон не найден')
                is_test=bool(status[1]);status=status[0]
                if path=='/api/reset-test':
                    if not is_test or y==2026:raise ValueError('Сброс разрешён только тестовым сезонам')
                    if d.get('confirm')!=str(y):raise ValueError('Подтвердите номер сезона')
                    c.execute('DELETE FROM ballot WHERE year=?',(y,));c.execute('DELETE FROM participation WHERE year=?',(y,));c.execute("UPDATE season SET status='draft' WHERE year=?",(y,));c.commit();return self.send({'ok':True})
                if path=='/api/dashboard':
                    a=rows(c,'SELECT e.id,e.name,e.city,e.active,COALESCE(p.used,0) used,CASE WHEN p.code_hash IS NULL THEN 0 ELSE 1 END issued FROM employee e LEFT JOIN participation p ON e.id=p.employee AND p.year=? ORDER BY e.name',(y,));r=rows(c,'SELECT e.name,e.city,COUNT(*) votes FROM ballot b JOIN employee e ON e.id=b.candidate WHERE b.year=? GROUP BY e.id ORDER BY votes DESC,e.name',(y,)) if status=='closed' else [];return self.send({'employees':a,'ranking':r,'status':status,'is_test':is_test})
                if path in ('/api/employee-save','/api/employee-toggle'):
                    if c.execute("SELECT 1 FROM season WHERE status='open'").fetchone():raise ValueError('Изменение справочника доступно только вне открытого голосования')
                    eid=str(d.get('id','')).strip();name=str(d.get('name','')).strip();city=str(d.get('city','')).strip()
                    if not eid:raise ValueError('Введите табельный номер')
                    if path=='/api/employee-toggle':
                        if c.execute('UPDATE employee SET active=? WHERE id=?',(int(bool(d.get('active'))),eid)).rowcount!=1:raise ValueError('Сотрудник не найден')
                    else:
                        if not name or not city:raise ValueError('Заполните ФИО и подразделение')
                        if d.get('edit'):
                            if c.execute('UPDATE employee SET name=?,city=? WHERE id=?',(name,city,eid)).rowcount!=1:raise ValueError('Сотрудник не найден')
                        else:c.execute('INSERT INTO employee(id,name,city) VALUES(?,?,?)',(eid,name,city))
                    c.commit();return self.send({'ok':True})
                if path=='/api/import':
                    if c.execute("SELECT 1 FROM season WHERE status='open'").fetchone():raise ValueError('Импорт доступен только вне открытого голосования')
                    a=import_employees(base64.b64decode(d['file'],validate=True));c.executemany('INSERT INTO employee(id,name,city) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,city=excluded.city,active=1',a);c.commit();return self.send({'count':len(a)})
                if path=='/api/codes':
                    if status=='closed':raise ValueError('Сезон завершён')
                    a=rows(c,'SELECT e.id,e.name,e.city FROM employee e LEFT JOIN participation p ON p.year=? AND p.employee=e.id WHERE e.active=1 AND COALESCE(p.used,0)=0 AND (?=\'\' OR e.city=?) AND (?=\'\' OR e.id=?) AND (p.code_hash IS NULL OR ?=1)',(y,d.get('city',''),d.get('city',''),d.get('employee',''),d.get('employee',''),int(bool(d.get('replace')))));out=[]
                    for e in a:
                        code=makecode();c.execute('INSERT INTO participation(year,employee,code_hash) VALUES(?,?,?) ON CONFLICT(year,employee) DO UPDATE SET code_hash=excluded.code_hash WHERE used=0',(y,e['id'],digest(code)));out.append([e['name'],e['city'],code])
                    w=Workbook();ws=w.active;ws.title='Коды';ws.append(['Сотрудник','Подразделение','Код']);
                    for row in out:ws.append(["'"+v if v.startswith(('=','+','-','@')) else v for v in row])
                    for col,width in [('A',42),('B',32),('C',28)]:ws.column_dimensions[col].width=width
                    buf=io.BytesIO();w.save(buf);c.commit();return self.send({'rows':out,'file':base64.b64encode(buf.getvalue()).decode()})
                if path=='/api/status':
                    new=d.get('status');allowed={'draft':'open','open':'closed'}
                    if allowed.get(status)!=new:raise ValueError('Недопустимый переход')
                    if new=='open' and not c.execute('SELECT 1 FROM participation WHERE year=?',(y,)).fetchone():raise ValueError('Сначала выдайте коды')
                    c.execute('UPDATE season SET status=? WHERE year=?',(new,y));c.commit();return self.send({'ok':True})
                if path=='/api/archive-import':
                    raw=base64.b64decode(d['file'],validate=True);bid=hashlib.sha256(raw).hexdigest()
                    if c.execute('SELECT 1 FROM archive_batch WHERE id=?',(bid,)).fetchone():raise ValueError('Этот файл уже импортирован')
                    wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True);ws=wb.active;it=iter(ws.values);header=next(it,())
                    if len(header)<4 or not all('сотрудника' in str(x).lower() for x in header[1:4]):raise ValueError('Ожидается архив Google Forms с тремя колонками кандидатов')
                    counts={}
                    for row in it:
                        for value in row[1:4]:
                            raw_name=str(value or '').strip()
                            if raw_name:counts[raw_name]=counts.get(raw_name,0)+1
                    if not counts:raise ValueError('Нет ответов')
                    c.execute('INSERT INTO archive_batch VALUES(?,?)',(bid,str(d.get('label','Архив'))[:150]))
                    people=rows(c,'SELECT id,name FROM employee')
                    for name,n in counts.items():
                        tokens=norm(name).split()
                        exact=[p for p in people if sorted(tokens)==sorted(norm(p['name']).split())]
                        eid=exact[0]['id'] if len(exact)==1 else None
                        c.execute('INSERT INTO archive_name VALUES(?,?,?,?)',(bid,name,n,eid))
                    c.commit();return self.send({'ok':True})
                if path=='/api/archive-match':
                    eid=str(d.get('employee','')) or None
                    if eid and not c.execute('SELECT 1 FROM employee WHERE id=?',(eid,)).fetchone():raise ValueError('Сотрудник не найден')
                    if c.execute('UPDATE archive_name SET employee=? WHERE batch=? AND raw=?',(eid,d.get('batch'),d.get('raw'))).rowcount!=1:raise ValueError('Запись не найдена')
                    c.commit();return self.send({'ok':True})
                if path=='/api/archive':
                    return self.send({'batches':rows(c,'SELECT * FROM archive_batch ORDER BY label'),'names':rows(c,'SELECT * FROM archive_name ORDER BY n DESC,raw')})
                if path=='/api/backup':
                    # SQLite online backup, only authenticated administrators; no public path.
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmp:
                        target=Path(tmp)/'backup.sqlite3';dest=sqlite3.connect(target)
                        try:c.backup(dest)
                        finally:dest.close()
                        return self.send({'file':base64.b64encode(target.read_bytes()).decode()})
                if path=='/api/export':
                    kind=d.get('kind');w=Workbook();ws=w.active
                    if kind=='pending':
                        ws.append(['Сотрудник','Подразделение']);a=c.execute('SELECT e.name,e.city FROM employee e LEFT JOIN participation p ON p.employee=e.id AND p.year=? WHERE e.active=1 AND COALESCE(p.used,0)=0 AND (?=\'\' OR e.city=?) ORDER BY e.city,e.name',(y,d.get('city',''),d.get('city','')))
                    elif kind=='ranking' and status=='closed':
                        ws.append(['Сотрудник','Подразделение','Голоса']);a=c.execute('SELECT e.name,e.city,COUNT(*) FROM ballot b JOIN employee e ON e.id=b.candidate WHERE b.year=? GROUP BY e.id ORDER BY COUNT(*) DESC,e.name',(y,))
                    else:raise ValueError('Отчёт недоступен')
                    for row in a:ws.append(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
                    buf=io.BytesIO();w.save(buf);return self.send({'file':base64.b64encode(buf.getvalue()).decode()})
                return self.send({'error':'Нет маршрута'},404)
        except ValueError as e:self.send({'error':str(e)},400)
        except (sqlite3.Error,KeyError,TypeError):self.send({'error':'Операция не выполнена. Проверьте данные.'},400)
if __name__=='__main__':
    if len(ADMIN)<16:raise SystemExit('Укажите ADMIN_PASSWORD длиной от 16 символов')
    init();ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),H).serve_forever()
