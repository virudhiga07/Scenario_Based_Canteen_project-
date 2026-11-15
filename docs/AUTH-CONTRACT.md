# Authentication addition contract
User requests accounts (canteen name, owner name, mobile, GSTIN, password), logout, mobile OTP password reset, responsive screens.

Fields: canteen_name 2..100 trimmed; owner_name 2..100; mobile exactly10 digits (normalize optional +91); gst_number uppercase15 alphanumeric characters. Demo registration accepts 1234567890 and 1234567890OKJHG without phone-prefix or GST checksum restrictions. Password8..128 characters, never trimmed, never stored or returned plaintext. Registration checks do not verify government GST registration or mobile ownership. Frontend auth forms use custom inline validation instead of native format popups.

Routes under /api/auth:
GET /session -> {account:null|{id,canteen_name,owner_name,mobile,gst_number},sms_available:boolean}
POST /register body{canteen_name,owner_name,mobile,gst_number,password} ->201 {account}; sets cookie
POST /login body{mobile,password} ->200 {account}; sets cookie
POST /logout ->200 {ok:true}; destroys session and cookie
POST /forgot-password body{mobile} ->200 {message:'If an account exists, a verification code will be sent.',challenge_id,expires_in:600,resend_after:60}. For unknown phones return indistinguishable dummy challenge; no SMS. Provider absent returns503 {error:'SMS verification is not configured yet. Please contact the canteen administrator.'} on all numbers. Never return OTP.
POST /reset-password body{challenge_id,mobile,otp,password} ->200 {ok:true,message:'Password updated. Sign in with your new password.'}. Does not log in. Requires6-digitOTP, expires10min, at most5 attempts. Provider verifies realOTP. Success consumes challenge, changes salted hash, revokes ALL sessions.
All errors JSON {error}. Unauthorized protected API401. Protected user data endpoints require session even reads. Logout returns200 when already logged out. Same-origin write validation. HTTP-only SameSite=Strict cookie `canteen_session`, Secure on HTTPS, path=/, max-age604800. Session raw256-bit random value hashed SHA256 in DB. Password PBKDF2 SHA256100000 iterations (Worker WebCrypto supported maximum), 16byte random salt,32byte output serialized `pbkdf2-sha256$100000$base64salt$base64hash`. Java implementation equivalent.

New tables in database/auth.sql (root supplies) and new immutable drizzle migration:
accounts(id TEXT PK,canteen_name TEXT,owner_name TEXT,mobile TEXT UNIQUE,gst_number TEXT UNIQUE,password_hash TEXT,created_at INTEGER)
auth_sessions(token_hash TEXT PK,account_id TEXT FK accounts,expires_at INTEGER,created_at INTEGER)
auth_rate_limits(key TEXT PK,window_start INTEGER,attempts INTEGER)
password_reset_challenges(id TEXT PK,account_id TEXT nullable FK accounts,mobile TEXT,expires_at INTEGER,attempts INTEGER DEFAULT0,consumed INTEGER DEFAULT0,created_at INTEGER)
ALTER menu_items ADD COLUMN account_id TEXT REFERENCES accounts(id);
ALTER orders ADD COLUMN account_id TEXT REFERENCES accounts(id);
Legacy rows remain account_id NULL and preserved; never expose to new accounts. New accounts get their own copy of the12 seed menu items, with no sample orders. All menu/order/sales operations scoped to authenticated account.id. Initial current seed initialization no longer runs in hosted handleApi. Python can filter account_id when desired; existing seed-only analysis unchanged.

SMS Twilio Verify REST, env TWILIO_ACCOUNT_SID,TWILIO_AUTH_TOKEN,TWILIO_VERIFY_SERVICE_SID. No real creds yet, no fake OTP mode permitted. Production recovery explicitly disabled until configured. Test provider injected server-side only, not via HTTP flags. Twilio6digit verify checks and service default10minexpiry. Limit forgot sends: perphone1/min +5/hour, IP20/hour; login5/phone/15min +30/IP/15min; register5/IP/hour. Store only hashed mobile/IP rate keys where practical. Auth handlers return generic auth errors. Failed sends must report failure and not pretend message sent.

Frontend initial session fetch before data. When logged out render login/register/forgot/OTP panels and hide operator app; no stored cart/account data survives logout. logout button both desktop and mobile. Session401 clears UI, preserves no sensitive data. Live form errors accessible, password toggles, optional confirm password client validation. Display canteen/owner names safely. Handle session expiry. No API secrets client side. GST example use validated sample from tests.

## User-approved demo OTP mode (supersedes provider-only requirements above)
AUTH_RECOVERY_MODE defaults to demo; explicit sms enables Twilio. GET session includes recovery_mode. Demo codes are CSPRNG6digits and returned as demo_otp plus demo:true only to browser holding recoverydevicecookie for requestedaccount. NoSMSsent label. Registration/passwordlogin set HttpOnly sameSiteStrict canteen_demo_recovery256bit30daycookie; storeSHA256 in demo_recovery_devices(token_hash PK,account_id FK,expires_at). Logout preserves recoverydevicecookie intentionally while destroying authsession. Demo forgottenrequest on otherbrowser returns403 with samebrowser requirement. Challenge table has demo_otp_hash SHA256(challenge_id+':'+code),recovery_token_hash,mode. Demo reset must have matching browsercookie hash and valid6digitcode, <=5attempts,600secondexpiry,atomicconsume, then change password, revoke ALL authsessions. Alltimefields Unixseconds. No publicfakeSMS credentials or unguarded reset. Newmode is explicitly disclosed in UI anddocs.
