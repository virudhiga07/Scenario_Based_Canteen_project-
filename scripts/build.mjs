import {readFile,writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
const root=resolve(import.meta.dirname,'..');
await mkdir(resolve(root,'dist/server'),{recursive:true});await mkdir(resolve(root,'dist/.openai'),{recursive:true});
const assets={};for(const [url,file,type]of [['/','web/index.html','text/html; charset=utf-8'],['/styles.css','web/styles.css','text/css'],['/app.js','web/app.js','application/javascript'],['/submission.zip','outputs/virudhigakv-canteen-submission.zip','application/zip']]){
 try{assets[url]={body:(await readFile(resolve(root,file))).toString('base64'),type}}catch(e){if(url==='/submission.zip')continue;throw e}
}
const seed=JSON.parse(await readFile(resolve(root,'database/seed.json'),'utf8'));
const auth=await readFile(resolve(root,'server/auth.mjs'),'utf8');
const api=(await readFile(resolve(root,'server/api.mjs'),'utf8')).replace(/^import .*auth\.mjs';\n/, '');
const entry=`${auth}\n${api}\nconst seed=${JSON.stringify(seed)};\nconst assets=${JSON.stringify(assets)};\nexport default {async fetch(request,env){const path=new URL(request.url).pathname;if(path.startsWith('/api/'))return handleApi(request,env.DB,seed,env);if(!['GET','HEAD'].includes(request.method))return new Response('Method not allowed',{status:405});const asset=assets[path==='/index.html'?'/':path];if(!asset)return new Response('Not found',{status:404});const bytes=Uint8Array.from(atob(asset.body),c=>c.charCodeAt(0));return new Response(request.method==='HEAD'?null:bytes,{headers:{'Content-Type':asset.type,'X-Content-Type-Options':'nosniff','Cache-Control':'no-cache',...(path==='/submission.zip'?{'Content-Disposition':'attachment; filename="virudhigakv-canteen-submission.zip"'}:{})}})}};\n`;
await writeFile(resolve(root,'dist/server/index.js'),entry);
await cp(resolve(root,'.openai/hosting.json'),resolve(root,'dist/.openai/hosting.json'));
await cp(resolve(root,'drizzle'),resolve(root,'dist/drizzle'),{recursive:true});
await writeFile(resolve(root,'dist/server/wrangler.json'),JSON.stringify({name:'campus-canteen',main:'index.js',compatibility_date:'2026-01-01',d1_databases:[{binding:'DB',database_name:'campus-canteen',database_id:'local',migrations_dir:'../drizzle'}]},null,2));
console.log('Built self-contained Worker with '+Object.keys(assets).length+' assets and D1 migrations.');
