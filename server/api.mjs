import {handleAuth, requireAccount, AuthError} from './auth.mjs';
/** Shared hosted API. D1 batch() commits all statements atomically. */
export class ApiError extends Error { constructor(status,message){ super(message);this.status=status; } }
const fail=(status,message)=>{throw new ApiError(status,message)};
const text=(value,name,max=100,optional=false)=>{if(typeof value!=='string'||value.trim().length>max||(!optional&&!value.trim()))fail(400,`${name} must be ${optional?'at most':'between 1 and'} ${max} characters.`);return value.trim()};
const integer=(value,name,min,max)=>{if(!Number.isSafeInteger(value)||value<min||value>max)fail(400,`${name} must be a whole number from ${min} to ${max}.`);return value};
const json=(data,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
const all=async(db,sql,args=[])=> (await db.prepare(sql).bind(...args).all()).results;
const first=async(db,sql,args=[])=>db.prepare(sql).bind(...args).first();
function normalizeOrder(body){
 if(!body||typeof body!=='object'||Array.isArray(body))fail(400,'An order object is required.');
 const id=text(body.id,'Order ID',80);
 if(!/^[a-zA-Z0-9_-]{8,80}$/.test(id))fail(400,'Provide a valid unique order ID.');
 const customer_name=text(body.customer_name||'Walk-in','Customer name');
 if(!['Dine-in','Takeaway'].includes(body.order_type))fail(400,'Choose Dine-in or Takeaway.');
 if(!['Cash','UPI','Card'].includes(body.payment_method))fail(400,'Choose Cash, UPI or Card.');
 if(!Array.isArray(body.items)||!body.items.length||body.items.length>100)fail(400,'Choose between 1 and 50 different menu items.');
 const totals=new Map();for(const item of body.items){if(!item||typeof item!=='object')fail(400,'Invalid order item.');const id=integer(item.item_id,'Item ID',1,2147483647),quantity=integer(item.quantity,'Quantity',1,10000);totals.set(id,(totals.get(id)||0)+quantity);if(totals.get(id)>10000)fail(400,'Total quantity per item cannot exceed 10000.');}
 if(totals.size>50)fail(400,'Choose no more than 50 different menu items.');
 return {id,customer_name,order_type:body.order_type,payment_method:body.payment_method,items:[...totals.entries()].sort((a,b)=>a[0]-b[0]).map(([item_id,quantity])=>({item_id,quantity}))};
}
async function getOrder(db,id,accountId){const order=await first(db,'SELECT * FROM orders WHERE id=? AND account_id=?',[id,accountId]);if(!order)return null;order.items=await all(db,'SELECT item_id,item_name,quantity,unit_price_paise FROM order_items WHERE order_id=? ORDER BY item_id',[id]);return order;}
function sameOrder(existing,order){return existing.customer_name===order.customer_name&&existing.order_type===order.order_type&&existing.payment_method===order.payment_method&&JSON.stringify(existing.items.map(({item_id,quantity})=>({item_id,quantity})))===JSON.stringify(order.items);}
async function createOrder(db,body,accountId){
 const o=normalizeOrder(body);let prior=await getOrder(db,o.id,accountId);
 if(prior){if(!sameOrder(prior,o))fail(409,'This order ID was already used for a different order.');return json({order:prior});}
 const entries=JSON.stringify(o.items),now=new Date().toISOString();
 // Header validation is inside the batch, so price, availability, lines and stock form one transaction.
 const validTotal=`SELECT CASE WHEN count(*)=? AND min(m.active)=1 AND min(m.stock >= json_extract(j.value,'$.quantity'))=1 THEN SUM(m.price_paise*json_extract(j.value,'$.quantity')) ELSE -1 END FROM json_each(?) j JOIN menu_items m ON m.id=json_extract(j.value,'$.item_id') WHERE m.account_id=?`;
 try{
 await db.batch([
 db.prepare(`INSERT INTO orders(id,customer_name,order_type,payment_method,created_at,total_paise,is_demo,account_id) VALUES(?,?,?,?,?,(${validTotal}),0,?)`).bind(o.id,o.customer_name,o.order_type,o.payment_method,now,o.items.length,entries,accountId,accountId),
 db.prepare("INSERT INTO order_items(order_id,item_id,item_name,quantity,unit_price_paise) SELECT ?,m.id,m.name,json_extract(j.value,'$.quantity'),m.price_paise FROM json_each(?) j JOIN menu_items m ON m.id=json_extract(j.value,'$.item_id') WHERE m.account_id=?").bind(o.id,entries,accountId),
 db.prepare("UPDATE menu_items SET stock=stock-(SELECT json_extract(j.value,'$.quantity') FROM json_each(?) j WHERE json_extract(j.value,'$.item_id')=menu_items.id) WHERE id IN (SELECT json_extract(value,'$.item_id') FROM json_each(?)) AND account_id=?").bind(entries,entries,accountId)
 ]);
 }catch(error){prior=await getOrder(db,o.id,accountId);if(prior){if(!sameOrder(prior,o))fail(409,'This order ID was already used for a different order.');return json({order:prior});}if(/constraint|check|total_paise/i.test(String(error)))fail(409,'Some items are unavailable or have insufficient stock. Refresh the menu and try again.');throw error;}
 return json({order:await getOrder(db,o.id,accountId)},201);
}
function normalizeMenu(body){if(!body||typeof body!=='object')fail(400,'A menu item object is required.');return {name:text(body.name,'Name'),category:text(body.category,'Category',40),description:text(body.description??'','Description',300,true),price_paise:integer(body.price_paise,'Price in paise',1,10000000),stock:integer(body.stock,'Stock',0,1000000),image:text(body.image??'','Image identifier',500,true),active:integer(body.active??1,'Active status',0,1)};}
export async function handleApi(request,db,seed,env={}){
 try{
 const url=new URL(request.url),path=url.pathname,method=request.method;
 if(method!=='GET'&&request.headers.get('Sec-Fetch-Site')==='cross-site')fail(403,'Cross-origin writes are not allowed.');
 if(method!=='GET'&&request.headers.has('Origin')&&request.headers.get('Origin')!==url.origin)fail(403,'Cross-origin writes are not allowed.');
 if(path==='/api/health')return json({ok:true});
 if(!db)fail(503,'The database binding is not configured.');
 let body;
 if(['POST','PATCH'].includes(method)){if(request.headers.get('Content-Type')?.split(';')[0]!=='application/json')fail(415,'Send JSON with Content-Type application/json.');const raw=await request.text();if(raw.length>65536)fail(413,'Request body too large.');try{body=JSON.parse(raw)}catch{fail(400,'Request body must be valid JSON.');}}
 if(path.startsWith('/api/auth/'))return await handleAuth(request,db,seed,body,env);
 const account=await requireAccount(request,db);
 if(path==='/api/menu'&&method==='GET')return json({items:await all(db,'SELECT * FROM menu_items WHERE account_id=? ORDER BY id',[account.id])});
 if(path==='/api/orders'&&method==='GET'){
 const [orders,items]=await Promise.all([all(db,'SELECT * FROM orders WHERE account_id=? ORDER BY created_at DESC,id DESC',[account.id]),all(db,'SELECT i.* FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.account_id=? ORDER BY i.item_id',[account.id])]);const byId=new Map(orders.map(o=>[o.id,{...o,items:[]}]));for(const {order_id,...item}of items)byId.get(order_id)?.items.push(item);return json({orders:[...byId.values()]});
 }
 if(path==='/api/orders'&&method==='POST')return await createOrder(db,body,account.id);
 if(path==='/api/sales'&&method==='GET')return json({lines:await all(db,'SELECT o.id AS order_id,o.created_at,o.customer_name,o.order_type,o.payment_method,o.is_demo,i.item_id,i.item_name,i.quantity,i.unit_price_paise,i.quantity*i.unit_price_paise AS line_total_paise FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.account_id=? ORDER BY o.created_at,i.item_id',[account.id])});
 if(path==='/api/menu'&&method==='POST'){const item=normalizeMenu(body);const row=await db.prepare('INSERT INTO menu_items(name,category,description,price_paise,stock,image,active,account_id) VALUES(?,?,?,?,?,?,?,?) RETURNING *').bind(...Object.values(item),account.id).first();return json({item:row},201);}
 if(/^\/api\/menu\/\d+$/.test(path)&&method==='PATCH'){const id=integer(Number(path.split('/').at(-1)),'Item ID',1,2147483647),item=normalizeMenu(body);const row=await db.prepare('UPDATE menu_items SET name=?,category=?,description=?,price_paise=?,stock=?,image=?,active=? WHERE id=? AND account_id=? RETURNING *').bind(...Object.values(item),id,account.id).first();if(!row)fail(404,'Menu item not found.');return json({item:row});}
 fail(404,'API endpoint not found.');
 }catch(error){if(error instanceof ApiError||error instanceof AuthError)return json({error:error.message},error.status);console.error('Canteen API failure',error?.message);return json({error:'The database request could not be completed. Please try again.'},500);}
}
