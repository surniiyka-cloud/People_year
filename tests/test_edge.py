"""Live integration test. Uses only the isolated 2099 season and two synthetic IDs.
Run with PEOPLE_TEST_PASSWORD in the environment; never commit credentials.
The operator removes the synthetic fixture after this run using the management connection.
"""
import base64, concurrent.futures, io, json, os, urllib.request, urllib.error, unittest
from openpyxl import Workbook, load_workbook
URL=os.getenv('PEOPLE_TEST_URL','https://gsxroprhnimtrzjhvuah.supabase.co/functions/v1/people-api/')
YEAR=2099
A='__migration_test_a'
B='__migration_test_b'

def call(action, data=None, token=None, origin=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    if origin: headers['Origin']=origin
    req=urllib.request.Request(URL+action, data=None if data is None else json.dumps(data).encode(),headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=90) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)

def excel(rows):
    w=Workbook();s=w.active
    for row in rows:s.append(row)
    b=io.BytesIO();w.save(b);return base64.b64encode(b.getvalue()).decode()

class EdgeTests(unittest.TestCase):
    def test_complete_flow(self):
        passed=[]
        def check(name, condition):
            self.assertTrue(condition,name);passed.append(name);print('PASS: '+name,flush=True)
        def admin(action, **data):
            code,result=call(action,{'year':YEAR,**data},token)
            self.assertEqual(code,200,action+': '+str(result.get('error','')))
            return result
        check('anonymous state',call('state')[1]=={'role':None})
        for route in ['dashboard','codes','backup','archive','export','employee-save','new-season','reset-test']:
            check('anonymous blocked '+route,call(route,{'year':YEAR})[0]==401)
        check('untrusted origin blocked',call('state',origin='https://attacker.example')[0]==403)
        code,result=call('admin-login',{'password':os.environ['PEOPLE_TEST_PASSWORD']})
        self.assertEqual(code,200);token=result['token']
        check('admin authenticated',call('state',token=token)[1]['role']=='admin')
        admin('new-season',is_test=True)
        book=excel([['Migration QA'],[1,'Тест Альфа',None,None,None,A],[2,'Тест Бета',None,None,None,B]])
        check('Excel employee import',admin('import',file=book)['count']==2)
        duplicate=excel([['Migration QA'],[1,'Тест Альфа',None,None,None,A],[2,'Тест Бета',None,None,None,A]])
        check('duplicate employee IDs rejected',call('import',{'year':YEAR,'file':duplicate},token)[0]==400)
        check('invalid Excel rejected',call('import',{'year':YEAR,'file':'aGVsbG8='},token)[0]==400)
        issued=admin('codes',employee=A)
        code_a=issued['rows'][0][2]
        codes_book=load_workbook(io.BytesIO(base64.b64decode(issued['file'])))
        check('Excel codes export',codes_book.active.cell(2,3).value==code_a)
        code_b=admin('codes',employee=B)['rows'][0][2]
        check('code not disclosed twice',len(admin('codes',employee=A)['rows'])==0)
        admin('status',status='open')
        check('employee changes blocked during open season',call('employee-save',{'year':YEAR,'id':A,'name':'Changed','city':'QA','edit':True},token)[0]==400)
        v=call('login',{'code':code_a.lower()})[1]['token']
        check('voter state',call('state',token=v)[1]['used'] is False)
        check('voter admin access blocked',call('dashboard',{'year':YEAR},v)[0]==403)
        check('self omitted from search',all(e['id']!=A for e in call('search',{'q':'Тест'},v)[1]['employees']))
        check('self vote rejected',call('vote',{'candidate':A},v)[0]==400)
        check('unknown candidate rejected',call('vote',{'candidate':'does-not-exist'},v)[0]==400)
        check('ranking hidden before close',admin('dashboard')['ranking']==[])
        check('early ranking export blocked',call('export',{'year':YEAR,'kind':'ranking'},token)[0]==400)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(lambda _:call('vote',{'candidate':B},v)[0],range(5)))
        check('five concurrent votes record exactly one ballot',results.count(200)==1 and results.count(400)==4)
        check('used flag preserved',call('state',token=v)[1]['used'] is True)
        check('repeat vote rejected',call('vote',{'candidate':B},v)[0]==400)
        old=call('login',{'code':code_b})[1]['token']
        code_new=admin('codes',employee=B,replace=True)['rows'][0][2]
        check('reissued code revokes old code',call('login',{'code':code_b})[0]==400)
        check('reissued code revokes old session',call('state',token=old)[1]['role'] is None)
        fresh=call('login',{'code':code_new})[1]['token']
        check('new code works',call('state',token=fresh)[1]['role']=='voter')
        pending=admin('export',kind='pending')['file']
        check('pending export is valid XLSX',load_workbook(io.BytesIO(base64.b64decode(pending))).active.max_row>=2)
        admin('reset-codes',confirm=str(YEAR))
        check('bulk revocation preserves votes',next(e for e in admin('dashboard')['employees'] if e['id']==A)['used']==1)
        check('bulk revocation revokes session',call('state',token=fresh)[1]['role'] is None)
        admin('status',status='closed')
        ranking=admin('dashboard')['ranking']
        check('closed ranking has exactly one vote',sum(e['votes'] for e in ranking)==1)
        check('ranking export valid',bool(admin('export',kind='ranking')['file']))
        check('closed season cannot reopen',call('status',{'year':YEAR,'status':'open'},token)[0]==400)
        check('production season cannot reset',call('reset-test',{'year':2026,'confirm':'2026'},token)[0]==400)
        archive=excel([['Время','ФИО сотрудника 1','ФИО сотрудника 2','ФИО сотрудника 3'],['now','Тест Альфа','Альфа Тест','Неизвестное Имя']])
        admin('archive-import',file=archive,label='__migration_test_archive')
        check('duplicate archive rejected',call('archive-import',{'year':YEAR,'file':archive},token)[0]==400)
        archives=admin('archive');batch=next(b['id'] for b in archives['batches'] if b['label']=='__migration_test_archive')
        names=[n for n in archives['names'] if n['batch']==batch]
        check('archive exact normalized matches',sum(n['n'] for n in names if n['employee']==A)==2)
        admin('archive-match',batch=batch,raw='Неизвестное Имя',employee=B)
        check('archive manual match',any(n['raw']=='Неизвестное Имя' and n['employee']==B for n in admin('archive')['names']))
        snapshot=json.loads(base64.b64decode(admin('backup')['file']))
        check('backup excludes sessions and admin credentials','session' not in snapshot and 'admin_credential' not in snapshot)
        admin('reset-test',confirm=str(YEAR))
        check('test reset clears only isolated votes',admin('dashboard')['ranking']==[])
        admin('employee-toggle',id=A,active=False)
        check('employee deactivation',next(e for e in admin('dashboard')['employees'] if e['id']==A)['active']==0)
        admin('employee-toggle',id=A,active=True)
        admin('employee-save',id=A,name='Тест Альфа',city='Migration QA',edit=True)
        check('logout',call('logout',{},token)[0]==200 and call('state',token=token)[1]['role'] is None)
        print(json.dumps({'passed':passed,'count':len(passed)},ensure_ascii=False))

if __name__=='__main__':unittest.main()
