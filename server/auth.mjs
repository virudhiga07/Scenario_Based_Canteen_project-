// Password and session handling. Demo OTP is restricted to a previously authorized browser.
export class AuthError extends Error { constructor(status,message){super(message);this.status=status;} }
const authFail=(s,m)=>{throw new AuthError(s,m)};
const authNow=()=>Math.floor(Date.now()/1000);
const authOne=(db,sql,args=[])=>db.prepare(sql).bind(...args).first();
const authB64=bytes=>btoa(String.fromCharCode(...bytes));
const authBytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const authRandom=(size=32)=>crypto.getRandomValues(new Uint8Array(size));
const authToken=()=>authB64(authRandom()).replace(/\+/g,'-').replace(/\//g,'_').replace(/=/g,'');
export const authDigest=async s=>authB64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s))));
const authEqual=(a,b)=>{let diff=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0;};
export function authMobile(v){if(typeof v!=='string')authFail(400,'Enter a 10-digit mobile number.');let s=v.trim().replace(/[\s-]/g,'');if(s.startsWith('+91'))s=s.slice(3);if(!/^\d{10}$/.test(s))authFail(400,'Mobile number must contain exactly 10 digits.');return s;}
export function authGst(v){const s=typeof v==='string'?v.trim().toUpperCase():'';if(!/^[A-Z0-9]{15}$/.test(s))authFail(400,'GST number must contain exactly 15 letters or digits.');return s;}
function authName(v,label){if(typeof v!=='string'||v.trim().length<2||v.trim().length>100)authFail(400,`${label} must be between 2 and 100 characters.`);return v.trim();}
function authPassword(v){if(typeof v!=='string'||v.length<8||v.length>128)authFail(400,'Password must contain 8 to 128 characters.');return v;}
export async function authHash(password){const salt=authRandom(16),key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',iterations:100000,salt},key,256);return `pbkdf2-sha256$100000$${authB64(salt)}$${authB64(new Uint8Array(bits))}`;}
async function authVerify(password,stored){try{const[alg,rounds,salt,hash]=stored.split('$');if(alg!=='pbkdf2-sha256'||Number(rounds)!==100000)return false;const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',iterations:100000,salt:authBytes(salt)},key,256);return authEqual(authB64(new Uint8Array(bits)),hash);}catch{return false}}
export function authCookie(request,name){const parts=(request.headers.get('Cookie')||'').split(';');for(const part of parts){const i=part.indexOf('=');if(part.slice(0,i).trim()===name){const v=part.slice(i+1).trim();return /^[A-Za-z0-9_-]{43}$/.test(v)?v:null;}}return null;}
function authSetCookie(request,name,token,age){return `${name}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${age}${new URL(request.url).protocol==='https:'?'; Secure':''}`;}
function authResponse(data,status=200,cookies=[]){const headers=new Headers({'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});for(const c of cookies)headers.append('Set-Cookie',c);return new Response(JSON.stringify(data),{status,headers});}
const authPublic=a=>({id:a.id,canteen_name:a.canteen_name,owner_name:a.owner_name,mobile:a.mobile,gst_number:a.gst_number});
export async function requireAccount(request,db,optional=false){const token=authCookie(request,'canteen_session');const a=token?await authOne(db,'SELECT a.* FROM auth_sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>?',[await authDigest(token),authNow()]):null;if(!a&&!optional)authFail(401,'Please sign in to continue.');return a?authPublic(a):null;}
async function authRate(db,key,limit,window){const now=authNow(),start=Math.floor(now/window)*window;const row=await db.prepare('INSERT INTO auth_rate_limits(key,window_start,attempts) VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN window_start=excluded.window_start THEN attempts+1 ELSE 1 END,window_start=excluded.window_start RETURNING attempts').bind(await authDigest(key),start).first();if(row.attempts>limit)authFail(429,'Too many attempts. Please wait before trying again.');}
async function authSession(db,request,accountId){const now=authNow(),token=authToken(),device=authToken();await db.batch([db.prepare('INSERT INTO auth_sessions(token_hash,account_id,expires_at,created_at) VALUES(?,?,?,?)').bind(await authDigest(token),accountId,now+604800,now),db.prepare('INSERT INTO demo_recovery_devices(token_hash,account_id,expires_at) VALUES(?,?,?)').bind(await authDigest(device),accountId,now+2592000)]);return [authSetCookie(request,'canteen_session',token,604800),authSetCookie(request,'canteen_demo_recovery',device,2592000)];}
function authMode(env){const mode=env.AUTH_RECOVERY_MODE||'demo';if(!['demo','sms'].includes(mode))authFail(503,'Password recovery is not configured correctly.');return mode;}
function authSmsReady(env){return !!(env.TWILIO_ACCOUNT_SID&&env.TWILIO_AUTH_TOKEN&&env.TWILIO_VERIFY_SERVICE_SID);}
async function authSms(env,mobile,code){if(!authSmsReady(env))authFail(503,'SMS verification is not configured yet. Please contact the canteen administrator.');if(!/^VA[a-fA-F0-9]{32}$/.test(env.TWILIO_VERIFY_SERVICE_SID)||!/^AC[a-fA-F0-9]{32}$/.test(env.TWILIO_ACCOUNT_SID))authFail(503,'SMS verification is not configured correctly.');const values=new URLSearchParams({To:'+91'+mobile,...(code?{Code:code}:{Channel:'sms'})});let response;try{response=await fetch(`https://verify.twilio.com/v2/Services/${env.TWILIO_VERIFY_SERVICE_SID}/${code?'VerificationCheck':'Verifications'}`,{method:'POST',headers:{Authorization:'Basic '+btoa(env.TWILIO_ACCOUNT_SID+':'+env.TWILIO_AUTH_TOKEN),'Content-Type':'application/x-www-form-urlencoded'},body:values,signal:AbortSignal.timeout(10000)})}catch{authFail(503,'The SMS service is unavailable. Please try again later.');}if(!response.ok){if(code&&[400,404].includes(response.status))return false;authFail(503,'The SMS service could not complete this request. Please try again later.');}const data=await response.json();return code?data.status==='approved':true;}
function authOtp(){let n;do{n=crypto.getRandomValues(new Uint32Array(1))[0]}while(n>=4294000000);return String(n%1000000).padStart(6,'0');}
export async function handleAuth(request,db,seed,body,env={}){
 const path=new URL(request.url).pathname,method=request.method,mode=authMode(env),now=authNow();const ip=request.headers.get('CF-Connecting-IP')||'local';
 if(path==='/api/auth/session'&&method==='GET')return authResponse({account:await requireAccount(request,db,true),sms_available:authSmsReady(env),recovery_mode:mode});
 if(method!=='POST')authFail(404,'Authentication endpoint not found.');
 if(path==='/api/auth/logout'){const token=authCookie(request,'canteen_session');if(token)await db.prepare('DELETE FROM auth_sessions WHERE token_hash=?').bind(await authDigest(token)).run();return authResponse({ok:true},200,[authSetCookie(request,'canteen_session','',0)]);}
 if(!body||typeof body!=='object'||Array.isArray(body))authFail(400,'A JSON object is required.');
 if(path==='/api/auth/register'){
  await authRate(db,'register:'+ip,5,3600);const a={id:crypto.randomUUID(),canteen_name:authName(body.canteen_name,'Canteen name'),owner_name:authName(body.owner_name,'Owner name'),mobile:authMobile(body.mobile),gst_number:authGst(body.gst_number)};const hash=await authHash(authPassword(body.password));
  const statements=[db.prepare('INSERT INTO accounts(id,canteen_name,owner_name,mobile,gst_number,password_hash,created_at) VALUES(?,?,?,?,?,?,?)').bind(a.id,a.canteen_name,a.owner_name,a.mobile,a.gst_number,hash,now)];
  for(const item of seed.menu)statements.push(db.prepare('INSERT INTO menu_items(name,category,description,price_paise,stock,image,active,account_id) VALUES(?,?,?,?,?,?,?,?)').bind(item.name,item.category,item.description,item.price_paise,item.stock,item.image,item.active,a.id));
  try{await db.batch(statements)}catch(e){if(/unique|constraint/i.test(String(e)))authFail(409,'An account with this mobile number or GSTIN already exists. Sign in instead.');throw e;}
  return authResponse({account:a},201,await authSession(db,request,a.id));
 }
 if(path==='/api/auth/login'){
  const mobile=authMobile(body.mobile),password=authPassword(body.password);await authRate(db,'login-ip:'+ip,30,900);await authRate(db,'login-mobile:'+mobile,5,900);
  const account=await authOne(db,'SELECT * FROM accounts WHERE mobile=?',[mobile]);const dummy='pbkdf2-sha256$100000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';const valid=await authVerify(password,account?.password_hash||dummy);if(!account||!valid)authFail(401,'Mobile number or password is incorrect.');await db.prepare('DELETE FROM auth_rate_limits WHERE key=?').bind(await authDigest('login-mobile:'+mobile)).run();return authResponse({account:authPublic(account)},200,await authSession(db,request,account.id));
 }
 if(path==='/api/auth/forgot-password'){
  const mobile=authMobile(body.mobile);await authRate(db,'forgot-ip:'+ip,20,3600);const account=await authOne(db,'SELECT id FROM accounts WHERE mobile=?',[mobile]);const device=authCookie(request,'canteen_demo_recovery'),deviceHash=device?await authDigest(device):null;
  if(mode==='demo'){const known=account&&deviceHash?await authOne(db,'SELECT token_hash FROM demo_recovery_devices WHERE token_hash=? AND account_id=? AND expires_at>?',[deviceHash,account.id,now]):null;if(!known)authFail(403,'Demo recovery is available only in a browser where you created or signed in to this account.');}
  if(mode==='sms'&&!authSmsReady(env))authFail(503,'SMS verification is not configured yet. Please contact the canteen administrator.');
  await authRate(db,'forgot-minute:'+mobile,1,60);await authRate(db,'forgot-hour:'+mobile,5,3600);
  const id=crypto.randomUUID(),otp=mode==='demo'?authOtp():null;
  if(mode==='sms'&&account)await authSms(env,mobile);
  await db.batch([db.prepare('UPDATE password_reset_challenges SET consumed=1 WHERE account_id=? AND consumed=0').bind(account?.id??null),db.prepare('INSERT INTO password_reset_challenges(id,account_id,mobile,expires_at,created_at,demo_otp_hash,recovery_token_hash,mode) VALUES(?,?,?,?,?,?,?,?)').bind(id,account?.id??null,mobile,now+600,now,otp?await authDigest(id+':'+otp):null,mode==='demo'?deviceHash:null,mode)]);
  return authResponse({challenge_id:id,expires_in:600,resend_after:60,...(mode==='demo'?{demo:true,demo_otp:otp,message:'Demo code only — no SMS was sent.'}:{message:'If an account exists, a verification code will be sent.'})});
 }
 if(path==='/api/auth/reset-password'){
  const mobile=authMobile(body.mobile),password=authPassword(body.password);if(typeof body.otp!=='string'||!/^\d{6}$/.test(body.otp))authFail(400,'Enter the 6-digit verification code.');if(typeof body.challenge_id!=='string'||body.challenge_id.length>80)authFail(400,'Request a new verification code.');await authRate(db,'reset-ip:'+ip,30,900);
  const challenge=await authOne(db,'SELECT * FROM password_reset_challenges WHERE id=? AND mobile=?',[body.challenge_id,mobile]);if(!challenge||!challenge.account_id||challenge.consumed||challenge.expires_at<=now||challenge.attempts>=5)authFail(400,'This code is invalid or expired. Request a new code.');
  if(challenge.mode!==mode)authFail(400,'Recovery settings changed. Request a new code.');
  if(mode==='demo'){const cookie=authCookie(request,'canteen_demo_recovery'),digest=cookie?await authDigest(cookie):'';const known=await authOne(db,'SELECT token_hash FROM demo_recovery_devices WHERE token_hash=? AND account_id=? AND expires_at>?',[digest,challenge.account_id,now]);if(!known||!authEqual(digest,challenge.recovery_token_hash||''))authFail(403,'Use the browser where you requested this demo code.');}
  const attempted=await db.prepare('UPDATE password_reset_challenges SET attempts=attempts+1 WHERE id=? AND consumed=0 AND expires_at>? AND attempts<5 RETURNING attempts').bind(challenge.id,now).first();if(!attempted)authFail(400,'This code is invalid or expired. Request a new code.');
  const valid=mode==='demo'?authEqual(await authDigest(challenge.id+':'+body.otp),challenge.demo_otp_hash||''):await authSms(env,mobile,body.otp);if(!valid)authFail(400,'The verification code is incorrect.');
  const hash=await authHash(password);
  // All four statements share the same condition and commit atomically. No reset can reuse a consumed challenge.
  const condition='EXISTS(SELECT 1 FROM password_reset_challenges WHERE id=? AND consumed=0 AND expires_at>?)';
  const commitNow=authNow();
  const result=await db.batch([db.prepare(`UPDATE accounts SET password_hash=? WHERE id=? AND ${condition}`).bind(hash,challenge.account_id,challenge.id,commitNow),db.prepare(`DELETE FROM auth_sessions WHERE account_id=? AND ${condition}`).bind(challenge.account_id,challenge.id,commitNow),db.prepare(`DELETE FROM demo_recovery_devices WHERE account_id=? AND ${condition}`).bind(challenge.account_id,challenge.id,commitNow),db.prepare('UPDATE password_reset_challenges SET consumed=1 WHERE id=? AND consumed=0 AND expires_at>?').bind(challenge.id,commitNow)]);
  if(!result[0]?.meta?.changes)authFail(400,'This code has already been used or has expired.');
  return authResponse({ok:true,message:'Password updated. Sign in with your new password.'},200,[authSetCookie(request,'canteen_session','',0),authSetCookie(request,'canteen_demo_recovery','',0)]);
 }
 authFail(404,'Authentication endpoint not found.');
}
