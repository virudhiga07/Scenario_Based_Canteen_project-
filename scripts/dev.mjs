import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {handleApi} from '../server/api.mjs';
import {openDatabase} from '../server/sqlite-adapter.mjs';
const root=resolve(import.meta.dirname,'..');await mkdir(resolve(root,'.local'),{recursive:true});
const db=openDatabase(resolve(root,'.local/canteen.db'),await readFile(resolve(root,'database/schema.sql'),'utf8'));
// Apply repeatable CREATEs and missing ownership columns at startup.
const auth=await readFile(resolve(root,'database/auth.sql'),'utf8');
for(const statement of auth.split(';').map(s=>s.trim()).filter(Boolean)){
 const alter=statement.match(/^ALTER TABLE (menu_items|orders) ADD COLUMN account_id/);
 if(alter&&(await db.prepare('PRAGMA table_info('+alter[1]+')').all()).results.some(c=>c.name==='account_id'))continue;
 await db.prepare(statement).run();
}
const seed=JSON.parse(await readFile(resolve(root,'database/seed.json'),'utf8'));
const arg=(key,fallback)=>{const at=process.argv.indexOf(key);return at>=0?process.argv[at+1]:fallback};
const host=arg('--host','127.0.0.1'),port=Number(arg('--port','5173'));
createServer(async(req,res)=>{try{
 const url=new URL(req.url,`http://${req.headers.host}`);let response;
 if(url.pathname.startsWith('/api/')){let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>65536)break}response=await handleApi(new Request(url,{method:req.method,headers:req.headers,...(!['GET','HEAD'].includes(req.method)?{body:raw}:{})}),db,seed,process.env)}else{
 const paths={'/':'web/index.html','/index.html':'web/index.html','/styles.css':'web/styles.css','/app.js':'web/app.js','/submission.zip':'outputs/virudhigakv-canteen-submission.zip'};
 const file=paths[url.pathname];if(!file)response=new Response('Not found',{status:404});else{try{response=new Response(await readFile(resolve(root,file)),{headers:{'Content-Type':file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.zip')?'application/zip':'text/html; charset=utf-8'}})}catch{response=new Response('File is not ready',{status:404})}}
 }
 const headers=Object.fromEntries(response.headers);const cookies=response.headers.getSetCookie();if(cookies.length)headers['set-cookie']=cookies;res.writeHead(response.status,headers);res.end(Buffer.from(await response.arrayBuffer()));
 }catch(e){console.error(e);res.writeHead(500);res.end('Server error')}}).listen(port,host,()=>console.log(`Canteen preview on http://${host}:${port}`));
