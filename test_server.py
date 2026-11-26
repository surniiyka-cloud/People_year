import os,tempfile,threading,unittest,json,urllib.request,urllib.error,http.cookiejar,base64,io
from openpyxl import Workbook
import server
from http.cookiejar import CookieJar
class Tests(unittest.TestCase):
 def test_flow(self):
  with tempfile.TemporaryDirectory() as tmp:
   server.DB=tmp+'/db';server.ADMIN='test-long-password-123';server.SECURE=False;server.init();http=server.ThreadingHTTPServer(('127.0.0.1',0),server.H);threading.Thread(target=http.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{http.server_port}/api/'
   def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
   def call(c,p,d=None):
    req=urllib.request.Request(url+p,data=None if d is None else json.dumps(d).encode(),headers={'Content-Type':'application/json'});return json.load(c.open(req))
   try:
    admin=client();v=client();outsider=client();self.assertRaises(urllib.error.HTTPError,call,outsider,'dashboard',{'year':2026});call(admin,'admin-login',{'password':server.ADMIN})
    w=Workbook();s=w.active;s.append(['Офис тест']);s.append([1,'Иванов Иван Иванович',None,None,None,'001']);s.append([2,'Петров Пётр Петрович',None,None,None,'002']);b=io.BytesIO();w.save(b)
    self.assertEqual(call(admin,'import',{'year':2026,'file':base64.b64encode(b.getvalue()).decode()})['count'],2)
    codes=call(admin,'codes',{'year':2026})['rows'];code=next(r[2] for r in codes if r[0].startswith('Иванов'));call(admin,'status',{'year':2026,'status':'open'});call(v,'login',{'code':code});self.assertEqual(call(v,'search',{'q':'Иванов'})['employees'],[]);self.assertEqual(call(v,'search',{'q':'петр п'})['employees'][0]['id'],'002');self.assertRaises(urllib.error.HTTPError,call,v,'vote',{'candidate':'001'});self.assertRaises(urllib.error.HTTPError,call,v,'dashboard',{'year':2026});call(v,'vote',{'candidate':'002'});self.assertRaises(urllib.error.HTTPError,call,v,'vote',{'candidate':'002'});self.assertTrue(call(v,'state')['used']);d=call(admin,'dashboard',{'year':2026});self.assertEqual(sum(e['used'] for e in d['employees']),1);self.assertEqual(d['ranking'],[]);call(admin,'status',{'year':2026,'status':'closed'});self.assertEqual(call(admin,'dashboard',{'year':2026})['ranking'][0]['votes'],1);self.assertTrue(call(admin,'export',{'year':2026,'kind':'ranking'})['file']);self.assertTrue(call(admin,'export',{'year':2026,'kind':'pending'})['file']);print('PASS: import, codes, access, self-vote, repeat, participation, privacy, close, exports')
   finally:http.shutdown();http.server_close()
if __name__=='__main__':unittest.main()
