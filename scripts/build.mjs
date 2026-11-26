import {mkdir,copyFile,rm,readFile,writeFile} from 'node:fs/promises';
await rm('dist',{recursive:true,force:true});
await mkdir('dist/admin',{recursive:true});
for(const f of ['index.html','app.js','season-ui.js','style.css','favicon.svg'])await copyFile('static/'+f,'dist/'+f);
await writeFile('dist/.nojekyll','');
const html=await readFile('static/index.html','utf8');
await writeFile('dist/admin/index.html',html.replace('<head>','<head><base href="../">'));
console.log('Built GitHub Pages static assets; no database or server files included.');
