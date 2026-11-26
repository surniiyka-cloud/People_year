import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
test('turnout cards render current counts and handle unavailable data',async()=>{
 const context=vm.createContext({esc:v=>String(v),year:2026});
 vm.runInContext(await readFile('static/season-ui.js','utf8'),context);
 const html=vm.runInContext('turnoutCards({eligible:168,voted:1,pending:167,turnout:1})',context);
 assert.equal((html.match(/class="turnout-card"/g)||[]).length,4);
 for(const label of ['Допущены','Проголосовали','Ожидаются','Явка','168','167','1%'])assert.ok(html.includes(label));
 assert.ok(vm.runInContext('turnoutCards(null)',context).includes('временно недоступна'));
});
test('season controls distinguish code revocation and full restart',async()=>{
 const context=vm.createContext({year:2026});
 vm.runInContext(await readFile('static/season-ui.js','utf8'),context);
 const html=vm.runInContext('seasonControls()',context);
 assert.ok(html.includes('Обнулить коды'));
 assert.ok(html.includes('Начать сезон заново'));
 assert.ok(html.includes('резервный снимок'));
});
