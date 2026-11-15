import com.google.gson.*;
import java.io.*;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.sql.*;
import java.time.*;
import java.util.*;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/** Application authentication, separate from any hosting-platform identity. */
final class CanteenAuth {
    static final int ITERATIONS = 100000;
    static final long SESSION_SECONDS = 604800;
    static final String COOKIE = "canteen_session";
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final String ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    private static final String RESET_ERROR = "The code is invalid, expired, or has already been used. Request a new code.";
    private final String databaseUrl;
    private final Path root;
    private final SmsProvider sms;
    private final String recoveryMode;
    static final String RECOVERY_COOKIE = "canteen_demo_recovery";
    private final Object lock = new Object();
    interface SmsProvider {
        boolean available();
        void send(String mobile) throws Exception;
        boolean verify(String mobile, String code) throws Exception;
    }
    record Result(int status, Map<String,Object> data, List<String> cookies) {}
    static final class AuthError extends RuntimeException {
        final int status;
        AuthError(int status,String message) { super(message); this.status=status; }
    }
    CanteenAuth(String databaseUrl, Path root, SmsProvider sms) {
        this(databaseUrl,root,sms,System.getenv().getOrDefault("AUTH_RECOVERY_MODE","demo"));
    }
    CanteenAuth(String databaseUrl, Path root, SmsProvider sms, String mode) {
        this.databaseUrl=databaseUrl; this.root=root; this.sms=sms; this.recoveryMode=mode;
    }
    private Connection connect() throws SQLException {
        Connection c=DriverManager.getConnection(databaseUrl);
        try(Statement s=c.createStatement()) { s.execute("PRAGMA foreign_keys=ON"); s.execute("PRAGMA busy_timeout=10000"); }
        return c;
    }
    static SmsProvider environmentProvider() { return new TwilioVerify(System.getenv("TWILIO_ACCOUNT_SID"),System.getenv("TWILIO_AUTH_TOKEN"),System.getenv("TWILIO_VERIFY_SERVICE_SID")); }
    static String cookieToken(String header) { return cookieToken(header,COOKIE); }
    static String cookieToken(String header,String name) {
        if(header==null)return null;
        for(String part:header.split(";")) {
            String value=part.trim();
            if(value.startsWith(name+"=")) {String token=value.substring(name.length()+1);return token.matches("[A-Za-z0-9_-]{43}")?token:null;}
        }
        return null;
    }
    private static String recoveryCookie(String token,boolean secure) {return RECOVERY_COOKIE+"="+token+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+(token.isEmpty()?0:2592000)+(secure?"; Secure":"");}
    private static String cookie(String token,boolean secure) {return COOKIE+"="+token+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+(token.isEmpty()?0:SESSION_SECONDS)+(secure?"; Secure":"");}
    static long now() {return Instant.now().getEpochSecond();}
    Map<String,Object> account(String token) throws SQLException {
        if(token==null)return null;
        try(Connection c=connect()) {
            List<Map<String,Object>> found=rows(c,"SELECT a.id,a.canteen_name,a.owner_name,a.mobile,a.gst_number FROM accounts a JOIN auth_sessions s ON s.account_id=a.id WHERE s.token_hash=? AND s.expires_at>?",sha256(token),now());
            return found.isEmpty()?null:found.get(0);
        }
    }
    Map<String,Object> requireAccount(String token) throws SQLException {
        Map<String,Object> account=account(token);
        if(account==null)throw new AuthError(401,"Please sign in to continue.");
        return account;
    }
    Result handle(String path,String method,JsonObject body,String token,String recoveryToken,String remote,boolean secure) throws Exception {
        if(!Set.of("demo","sms").contains(recoveryMode))throw new AuthError(503,"Password recovery configuration is invalid. Contact the administrator.");
        if(path.equals("/api/auth/session")&&method.equals("GET")) {
            Map<String,Object> result=new LinkedHashMap<>();result.put("account",account(token));result.put("sms_available",sms.available());result.put("recovery_mode",recoveryMode);
            return new Result(200,result,List.of());
        }
        if(!method.equals("POST"))throw new AuthError(404,"Authentication endpoint not found.");
        if(path.equals("/api/auth/logout")) {
            if(token!=null)try(Connection c=connect()){execute(c,"DELETE FROM auth_sessions WHERE token_hash=?",sha256(token));}
            return new Result(200,Map.of("ok",true),List.of(cookie("",secure)));
        }
        if(body==null)throw new AuthError(400,"A JSON object is required.");
        return switch(path) {
            case "/api/auth/register" -> register(body,remote,secure);
            case "/api/auth/login" -> login(body,remote,secure);
            case "/api/auth/forgot-password" -> forgot(body,remote,recoveryToken);
            case "/api/auth/reset-password" -> reset(body,remote,recoveryToken,secure);
            default -> throw new AuthError(404,"Authentication endpoint not found.");
        };
    }
    private Result register(JsonObject b,String remote,boolean secure) throws Exception {
        String canteen=text(b,"canteen_name",2,100),owner=text(b,"owner_name",2,100),mobile=mobile(b),gst=gst(b),password=password(b);
        rate("register-ip",remote,5,3600);
        String passwordHash=hashPassword(password),id=UUID.randomUUID().toString(),session=randomToken(),device=randomToken();long now=now();
        JsonObject seed=JsonParser.parseString(Files.readString(root.resolve("database/seed.json"))).getAsJsonObject();
        synchronized(lock) {
            try(Connection c=connect()) {
                c.setAutoCommit(false);
                try {
                    execute(c,"INSERT INTO accounts(id,canteen_name,owner_name,mobile,gst_number,password_hash,created_at) VALUES(?,?,?,?,?,?,?)",id,canteen,owner,mobile,gst,passwordHash,now);
                    for(JsonElement element:seed.getAsJsonArray("menu")) {
                        JsonObject m=element.getAsJsonObject();
                        execute(c,"INSERT INTO menu_items(name,category,description,price_paise,stock,image,active,account_id) VALUES(?,?,?,?,?,?,?,?)",m.get("name").getAsString(),m.get("category").getAsString(),m.get("description").getAsString(),m.get("price_paise").getAsLong(),m.get("stock").getAsLong(),m.get("image").getAsString(),m.get("active").getAsInt(),id);
                    }
                    saveSession(c,session,id,now);saveRecoveryDevice(c,device,id,now);c.commit();
                }catch(SQLException e){c.rollback();if(e.getErrorCode()==19)throw new AuthError(409,"An account already uses this mobile number or GSTIN.");throw e;}
                catch(Exception e){c.rollback();throw e;}
            }
        }
        return new Result(201,Map.of("account",Map.of("id",id,"canteen_name",canteen,"owner_name",owner,"mobile",mobile,"gst_number",gst)),List.of(cookie(session,secure),recoveryCookie(device,secure)));
    }
    private Result login(JsonObject b,String remote,boolean secure) throws Exception {
        String mobile=mobile(b),password=rawPassword(b);
        rate("login-ip",remote,30,900);rate("login-mobile",mobile,5,900);
        Map<String,Object> found;
        try(Connection c=connect()){List<Map<String,Object>> matches=rows(c,"SELECT * FROM accounts WHERE mobile=?",mobile);found=matches.isEmpty()?null:matches.get(0);}
        // Do equivalent KDF work for an unknown account, without exposing whether it exists.
        String encoded=found==null?"pbkdf2-sha256$100000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=":(String)found.get("password_hash");
        boolean valid=verifyPassword(password,encoded);
        if(found==null||!valid)throw new AuthError(401,"Mobile number or password is incorrect.");
        String session=randomToken(),device=randomToken();
        synchronized(lock){try(Connection c=connect();Statement tx=c.createStatement()) {
            tx.execute("BEGIN IMMEDIATE");
            try {
                if(rows(c,"SELECT id FROM accounts WHERE id=? AND password_hash=?",found.get("id"),encoded).isEmpty())throw new AuthError(401,"Mobile number or password is incorrect.");
                saveSession(c,session,(String)found.get("id"),now());saveRecoveryDevice(c,device,(String)found.get("id"),now());
                execute(c,"DELETE FROM auth_sessions WHERE expires_at<=?",now());
                execute(c,"DELETE FROM auth_rate_limits WHERE key=?","login-mobile:"+sha256(mobile));
                tx.execute("COMMIT");
            }catch(Exception e){tx.execute("ROLLBACK");throw e;}
        }}
        return new Result(200,Map.of("account",publicAccount(found)),List.of(cookie(session,secure),recoveryCookie(device,secure)));
    }
    private Result forgot(JsonObject b,String remote,String recoveryToken) throws Exception {
        String mobile=mobile(b);
        if(recoveryMode.equals("sms"))requireSms();
        rate("reset-ip",remote,20,3600);
        String id=UUID.randomUUID().toString();String accountId=null;long now=now();
        try(Connection c=connect()) {List<Map<String,Object>> found=rows(c,"SELECT id FROM accounts WHERE mobile=?",mobile);if(!found.isEmpty())accountId=(String)found.get(0).get("id");}
        String code=null,deviceHash=null;
        if(recoveryMode.equals("demo")) {
            deviceHash=recoveryToken==null?null:sha256(recoveryToken);
            try(Connection c=connect()) {
                if(accountId==null||deviceHash==null||rows(c,"SELECT token_hash FROM demo_recovery_devices WHERE token_hash=? AND account_id=? AND expires_at>?",deviceHash,accountId,now).isEmpty())
                    throw new AuthError(403,"Demo recovery is available only in the same browser used to create or sign in to this account. Sign in once here or use real SMS verification when configured.");
            }
            code=String.format(Locale.ROOT,"%06d",RANDOM.nextInt(1000000));
        }
        rate("reset-mobile-hour",mobile,5,3600);rate("reset-mobile-minute",mobile,1,60);
        if(recoveryMode.equals("sms")&&accountId!=null) {
            try {sms.send(mobile);} catch(Exception e){throw new AuthError(502,"The verification code could not be sent. Please try again later.");}
        }
        try(Connection c=connect()) {
            c.setAutoCommit(false);
            try {
            execute(c,"DELETE FROM password_reset_challenges WHERE expires_at<=?",now);
            if(accountId!=null)execute(c,"UPDATE password_reset_challenges SET consumed=1 WHERE account_id=? AND consumed=0",accountId);
            execute(c,"INSERT INTO password_reset_challenges(id,account_id,mobile,expires_at,attempts,consumed,created_at,demo_otp_hash,recovery_token_hash,mode) VALUES(?,?,?,?,0,0,?,?,?,?)",id,accountId,mobile,now+600,now,code==null?null:sha256(id+":"+code),deviceHash,recoveryMode);
            c.commit();
            }catch(Exception e){c.rollback();throw e;}
        }
        Map<String,Object> data=new LinkedHashMap<>();data.put("message",code==null?"If an account exists, a verification code will be sent.":"Demo verification code generated. No SMS was sent.");data.put("challenge_id",id);data.put("expires_in",600);data.put("resend_after",60);
        if(code!=null){data.put("demo",true);data.put("demo_otp",code);}
        return new Result(200,data,List.of());
    }
    private Result reset(JsonObject b,String remote,String recoveryToken,boolean secure) throws Exception {
        String mobile=mobile(b),id=text(b,"challenge_id",8,100),code=text(b,"otp",6,6),password=password(b);
        if(!code.matches("[0-9]{6}"))throw new AuthError(400,"Enter the 6-digit verification code.");
        rate("verify-ip",remote,30,900);
        Map<String,Object> challenge;
        synchronized(lock){try(Connection c=connect()) {
            int changed=execute(c,"UPDATE password_reset_challenges SET attempts=attempts+1 WHERE id=? AND mobile=? AND expires_at>? AND consumed=0 AND attempts<5",id,mobile,now());
            if(changed!=1)throw new AuthError(400,RESET_ERROR);
            challenge=rows(c,"SELECT * FROM password_reset_challenges WHERE id=?",id).get(0);
        }}
        if(challenge.get("account_id")==null||!recoveryMode.equals(challenge.get("mode")))throw new AuthError(400,RESET_ERROR);
        boolean approved;
        if("demo".equals(challenge.get("mode"))) {
            String deviceHash=recoveryToken==null?null:sha256(recoveryToken);
            if(deviceHash==null||!deviceHash.equals(challenge.get("recovery_token_hash")))throw new AuthError(400,RESET_ERROR);
            try(Connection c=connect()) {if(rows(c,"SELECT token_hash FROM demo_recovery_devices WHERE token_hash=? AND account_id=? AND expires_at>?",deviceHash,challenge.get("account_id"),now()).isEmpty())throw new AuthError(400,RESET_ERROR);}
            approved=MessageDigest.isEqual(sha256(id+":"+code).getBytes(StandardCharsets.US_ASCII),String.valueOf(challenge.get("demo_otp_hash")).getBytes(StandardCharsets.US_ASCII));
        } else {
            requireSms();
            try {approved=sms.verify(mobile,code);} catch(Exception e){throw new AuthError(502,"Verification is temporarily unavailable. Please try again later.");}
        }
        if(!approved)throw new AuthError(400,RESET_ERROR);
        String hash=hashPassword(password),accountId=(String)challenge.get("account_id");
        synchronized(lock){try(Connection c=connect()) {
            c.setAutoCommit(false);
            try {
                if(execute(c,"UPDATE password_reset_challenges SET consumed=1 WHERE id=? AND mobile=? AND expires_at>? AND consumed=0",id,mobile,now())!=1)throw new AuthError(400,RESET_ERROR);
                execute(c,"UPDATE accounts SET password_hash=? WHERE id=?",hash,accountId);
                execute(c,"DELETE FROM auth_sessions WHERE account_id=?",accountId);
                execute(c,"DELETE FROM demo_recovery_devices WHERE account_id=?",accountId);
                execute(c,"UPDATE password_reset_challenges SET consumed=1 WHERE account_id=?",accountId);
                c.commit();
            }catch(Exception e){c.rollback();throw e;}
        }}
        return new Result(200,Map.of("ok",true,"message","Password updated. Sign in with your new password."),List.of(cookie("",secure),recoveryCookie("",secure)));
    }
    private void requireSms(){if(!sms.available())throw new AuthError(503,"SMS verification is not configured yet. Please contact the canteen administrator.");}
    private void rate(String scope,String subject,int limit,long seconds) throws SQLException {
        long now=now();String key=scope+":"+sha256(subject);
        try(Connection c=connect()) {
            execute(c,"INSERT INTO auth_rate_limits(key,window_start,attempts) VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN window_start<=? THEN 1 ELSE attempts+1 END,window_start=CASE WHEN window_start<=? THEN ? ELSE window_start END",key,now,now-seconds,now-seconds,now);
            long attempts=((Number)rows(c,"SELECT attempts FROM auth_rate_limits WHERE key=?",key).get(0).get("attempts")).longValue();
            if(attempts>limit)throw new AuthError(429,"Too many attempts. Please wait before trying again.");
        }
    }
    private static void saveRecoveryDevice(Connection c,String token,String accountId,long now) throws SQLException {execute(c,"DELETE FROM demo_recovery_devices WHERE expires_at<=?",now);execute(c,"INSERT INTO demo_recovery_devices(token_hash,account_id,expires_at) VALUES(?,?,?)",sha256(token),accountId,now+2592000);}
    private static void saveSession(Connection c,String token,String accountId,long now) throws SQLException {execute(c,"INSERT INTO auth_sessions(token_hash,account_id,expires_at,created_at) VALUES(?,?,?,?)",sha256(token),accountId,now+SESSION_SECONDS,now);}
    private static Map<String,Object> publicAccount(Map<String,Object> account) {Map<String,Object> safe=new LinkedHashMap<>();for(String key:List.of("id","canteen_name","owner_name","mobile","gst_number"))safe.put(key,account.get(key));return safe;}
    static String mobile(JsonObject b) {
        String value=text(b,"mobile",10,32).replaceAll("[\\s-]", "");
        if(value.startsWith("+91"))value=value.substring(3);
        if(!value.matches("[0-9]{10}"))throw new AuthError(400,"Enter exactly 10 digits for the mobile number.");
        return value;
    }
    static String gst(JsonObject b) {
        String value=text(b,"gst_number",15,15).toUpperCase(Locale.ROOT);
        if(!value.matches("[A-Z0-9]{15}"))throw new AuthError(400,"GST number must contain exactly 15 letters or digits.");
        return value;
    }
    static String rawPassword(JsonObject b) {JsonElement v=b.get("password");if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString()||v.getAsString().length()>128)throw new AuthError(400,"Password must contain 8–128 characters.");return v.getAsString();}
    static String password(JsonObject b) {String value=rawPassword(b);if(value.length()<8)throw new AuthError(400,"Password must contain 8–128 characters.");return value;}
    static String hashPassword(String password) throws GeneralSecurityException {
        byte[] salt=new byte[16];RANDOM.nextBytes(salt);
        return "pbkdf2-sha256$"+ITERATIONS+"$"+Base64.getEncoder().encodeToString(salt)+"$"+Base64.getEncoder().encodeToString(derive(password,salt,ITERATIONS));
    }
    static boolean verifyPassword(String password,String encoded) throws GeneralSecurityException {
        try {String[] parts=encoded.split("\\$");if(parts.length!=4||!parts[0].equals("pbkdf2-sha256")||Integer.parseInt(parts[1])!=ITERATIONS)return false;
            byte[] salt=Base64.getDecoder().decode(parts[2]),expected=Base64.getDecoder().decode(parts[3]);return MessageDigest.isEqual(derive(password,salt,ITERATIONS),expected);
        }catch(IllegalArgumentException e){return false;}
    }
    private static byte[] derive(String password,byte[] salt,int iterations) throws GeneralSecurityException {
        PBEKeySpec spec=new PBEKeySpec(password.toCharArray(),salt,iterations,256);
        try{return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();}finally{spec.clearPassword();}
    }
    private static String randomToken(){byte[] bytes=new byte[32];RANDOM.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);}
    static String sha256(String text){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}catch(GeneralSecurityException e){throw new IllegalStateException(e);}}
    private static String text(JsonObject body,String key,int min,int max) {JsonElement v=body.get(key);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString())throw new AuthError(400,key+" is required.");String text=v.getAsString().trim();if(text.length()<min||text.length()>max||text.chars().anyMatch(c->c<32))throw new AuthError(400,key+" must contain "+min+"–"+max+" characters.");return text;}
    private static int execute(Connection c,String query,Object...args) throws SQLException {try(PreparedStatement s=c.prepareStatement(query)){bind(s,args);return s.executeUpdate();}}
    private static List<Map<String,Object>> rows(Connection c,String query,Object...args) throws SQLException {try(PreparedStatement s=c.prepareStatement(query)){bind(s,args);try(ResultSet rs=s.executeQuery()){List<Map<String,Object>> rows=new ArrayList<>();ResultSetMetaData m=rs.getMetaData();while(rs.next()){Map<String,Object> r=new LinkedHashMap<>();for(int i=1;i<=m.getColumnCount();i++)r.put(m.getColumnLabel(i),rs.getObject(i));rows.add(r);}return rows;}}}
    private static void bind(PreparedStatement s,Object...args) throws SQLException {for(int i=0;i<args.length;i++)s.setObject(i+1,args[i]);}
    private static final class TwilioVerify implements SmsProvider {
        private final String account,token,service;
        private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
        TwilioVerify(String account,String token,String service){this.account=account;this.token=token;this.service=service;}
        public boolean available(){return account!=null&&account.matches("AC[0-9a-fA-F]{32}")&&token!=null&&!token.isBlank()&&service!=null&&service.matches("VA[0-9a-fA-F]{32}");}
        public void send(String mobile) throws Exception {JsonObject result=post("Verifications",Map.of("To","+91"+mobile,"Channel","sms"));if(!"pending".equals(result.get("status").getAsString()))throw new IOException("Unexpected SMS verification status");}
        public boolean verify(String mobile,String code) throws Exception {try {JsonObject result=post("VerificationCheck",Map.of("To","+91"+mobile,"Code",code));return result.has("status")&&"approved".equals(result.get("status").getAsString());}catch(TwilioMissing e){return false;}}
        private JsonObject post(String action,Map<String,String> fields) throws Exception {
            StringJoiner body=new StringJoiner("&");for(var field:fields.entrySet())body.add(URLEncoder.encode(field.getKey(),StandardCharsets.UTF_8)+"="+URLEncoder.encode(field.getValue(),StandardCharsets.UTF_8));
            String credentials=Base64.getEncoder().encodeToString((account+":"+token).getBytes(StandardCharsets.UTF_8));
            HttpRequest request=HttpRequest.newBuilder(URI.create("https://verify.twilio.com/v2/Services/"+service+"/"+action)).timeout(Duration.ofSeconds(15)).header("Authorization","Basic "+credentials).header("Content-Type","application/x-www-form-urlencoded").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build();
            HttpResponse<String> response=client.send(request,HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()==404)throw new TwilioMissing();
            if(response.statusCode()<200||response.statusCode()>=300)throw new IOException("SMS provider request failed");
            return JsonParser.parseString(response.body()).getAsJsonObject();
        }
    }
    private static final class TwilioMissing extends IOException {}
}
