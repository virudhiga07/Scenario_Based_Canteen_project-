import com.google.gson.*;
import com.google.gson.stream.JsonReader;
import com.google.gson.Strictness;
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Java 17+ canteen server. Money uses integer paise; JDBC transactions prevent overselling. */
public final class CanteenServer {
    private static final Gson JSON = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
    private final Path root;
    private final String databaseUrl;
    private final CanteenAuth auth;
    private final Object writeLock = new Object();
    private static final Set<String> ORDER_TYPES = Set.of("Dine-in", "Takeaway");
    private static final Set<String> PAYMENTS = Set.of("Cash", "UPI", "Card");
    private static final int MAX_BODY = 65536;

    private CanteenServer(Path root, Path db) throws Exception {
        this.root = root.toAbsolutePath().normalize();
        Path parent = db.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        this.databaseUrl = "jdbc:sqlite:" + db.toAbsolutePath();
        Class.forName("org.sqlite.JDBC");
        this.auth = new CanteenAuth(databaseUrl,this.root,CanteenAuth.environmentProvider());
    }
    public static void main(String[] args) throws Exception {
        Map<String,String> options = new HashMap<>();
        for (int i = 0; i < args.length; i += 2) {
            if (i + 1 == args.length || !Set.of("--db", "--port", "--root", "--seed", "--host").contains(args[i]))
                throw new IllegalArgumentException("Usage: --root PROJECT --db DATABASE --port PORT --seed none|PATH --host HOST");
            options.put(args[i], args[i+1]);
        }
        Path root = Path.of(options.getOrDefault("--root", ".."));
        Path db = Path.of(options.getOrDefault("--db", root.resolve("data/canteen.db").toString()));
        CanteenServer app = new CanteenServer(root, db);
        app.initialize(options.getOrDefault("--seed", root.resolve("database/seed.json").toString()));
        int port = Integer.parseInt(options.getOrDefault("--port", "8080"));
        String host = options.getOrDefault("--host", "127.0.0.1");
        HttpServer server = HttpServer.create(new InetSocketAddress(host, port), 0);
        server.createContext("/", app::handle);
        server.setExecutor(Executors.newFixedThreadPool(8));
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(1)));
        server.start();
        System.out.println("Campus Canteen running at http://" + host + ":" + server.getAddress().getPort());
        System.out.println("SQLite database: " + db.toAbsolutePath());
    }
    private Connection connect() throws SQLException {
        Connection c = DriverManager.getConnection(databaseUrl);
        try (Statement s = c.createStatement()) {
            s.execute("PRAGMA foreign_keys=ON");
            s.execute("PRAGMA busy_timeout=10000");
        }
        return c;
    }
    private void initialize(String seedPath) throws Exception {
        try (Connection c=connect();Statement s=c.createStatement()) {
            s.execute("PRAGMA journal_mode=WAL");
            for (String file:List.of("database/schema.sql","database/auth.sql")) {
                String schema=Files.readString(root.resolve(file));
                for(String raw:schema.replaceAll("(?m)--.*$", "").split(";")) {
                    String statement=raw.trim();if(statement.isEmpty())continue;
                    if(statement.startsWith("ALTER TABLE menu_items") && rows(c,"PRAGMA table_info(menu_items)").stream().anyMatch(row->"account_id".equals(row.get("name"))))continue;
                    if(statement.startsWith("ALTER TABLE orders") && rows(c,"PRAGMA table_info(orders)").stream().anyMatch(row->"account_id".equals(row.get("name"))))continue;
                    s.execute(statement);
                }
            }
            // Legacy rows remain unassigned. New accounts receive menu templates only.
            execute(c,"INSERT OR IGNORE INTO app_meta(key,value) VALUES('initialized','accounts-v1')");
        }
    }
    private void handle(HttpExchange exchange) throws IOException {
        try {
            String method=exchange.getRequestMethod(),path=exchange.getRequestURI().getPath();
            exchange.getResponseHeaders().set("X-Content-Type-Options","nosniff");
            exchange.getResponseHeaders().set("Referrer-Policy","same-origin");
            if(path.startsWith("/api/")) {
                exchange.getResponseHeaders().set("Cache-Control","no-store");
                if(!method.equals("GET"))checkOrigin(exchange);
                if(path.equals("/api/health")&&method.equals("GET")){sendJson(exchange,200,Map.of("ok",true));return;}
                String token=CanteenAuth.cookieToken(exchange.getRequestHeaders().getFirst("Cookie"));
                if(path.startsWith("/api/auth/")) {
                    JsonObject body=method.equals("POST")&&!path.equals("/api/auth/logout")?readBody(exchange):null;
                    String device=CanteenAuth.cookieToken(exchange.getRequestHeaders().getFirst("Cookie"),CanteenAuth.RECOVERY_COOKIE);
                    CanteenAuth.Result result=auth.handle(path,method,body,token,device,exchange.getRemoteAddress().getAddress().getHostAddress(),exchange instanceof HttpsExchange);
                    for(String cookie:result.cookies())exchange.getResponseHeaders().add("Set-Cookie",cookie);
                    sendJson(exchange,result.status(),result.data());return;
                }
                String accountId=(String)auth.requireAccount(token).get("id");
                Object result;
                if(path.equals("/api/menu")&&method.equals("GET")) {
                    try(Connection c=connect()){result=Map.of("items",rows(c,"SELECT * FROM menu_items WHERE account_id=? ORDER BY id",accountId));}
                } else if(path.equals("/api/menu")&&method.equals("POST"))result=saveMenu(readBody(exchange),null,accountId);
                else if(path.matches("/api/menu/[0-9]+")&&method.equals("PATCH")) {
                    long id;try{id=Long.parseLong(path.substring(path.lastIndexOf('/')+1));}catch(NumberFormatException e){throw new ApiError(400,"Invalid item ID.");}
                    result=saveMenu(readBody(exchange),id,accountId);
                } else if(path.equals("/api/orders")&&method.equals("POST"))result=placeOrder(readBody(exchange),accountId);
                else if(path.equals("/api/orders")&&method.equals("GET")) {
                    try(Connection c=connect()) {
                        List<Map<String,Object>> orders=rows(c,"SELECT * FROM orders WHERE account_id=? ORDER BY created_at DESC,id DESC",accountId);
                        for(Map<String,Object> order:orders)order.put("items",rows(c,"SELECT item_id,item_name,quantity,unit_price_paise FROM order_items WHERE order_id=? ORDER BY item_id",order.get("id")));
                        result=Map.of("orders",orders);
                    }
                } else if(path.equals("/api/sales")&&method.equals("GET")) {
                    try(Connection c=connect()){result=Map.of("lines",rows(c,"SELECT o.id AS order_id,o.created_at,o.customer_name,o.order_type,o.payment_method,o.is_demo,i.item_id,i.item_name,i.quantity,i.unit_price_paise,i.quantity*i.unit_price_paise AS line_total_paise FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.account_id=? ORDER BY o.created_at DESC,o.id,i.item_id",accountId));}
                } else throw new ApiError(404,"Endpoint not found.");
                sendJson(exchange,200,result);
            } else {
                if(!method.equals("GET")&&!method.equals("HEAD"))throw new ApiError(405,"Method not allowed.");
                serveFile(exchange,path,method.equals("HEAD"));
            }
        }catch(CanteenAuth.AuthError e){sendJson(exchange,e.status,Map.of("error",e.getMessage()));}
        catch(ApiError e){sendJson(exchange,e.status,Map.of("error",e.getMessage()));}
        catch(SQLException e){System.err.println("Database request failed: "+e.getClass().getSimpleName());sendJson(exchange,500,Map.of("error","Database operation failed. Please try again."));}
        catch(Exception e){System.err.println("Request failed: "+e.getClass().getSimpleName());sendJson(exchange,500,Map.of("error","Unable to process the request."));}
        finally{exchange.close();}
    }
    private static void checkOrigin(HttpExchange exchange) {
        String origin=exchange.getRequestHeaders().getFirst("Origin");
        String site=exchange.getRequestHeaders().getFirst("Sec-Fetch-Site");
        if ("cross-site".equals(site)) throw new ApiError(403,"Cross-origin writes are not permitted.");
        if (origin==null) return;
        try {
            URI uri=URI.create(origin);
            String host=exchange.getRequestHeaders().getFirst("Host");
            if (!(exchange instanceof HttpsExchange ? "https" : "http").equals(uri.getScheme()) || uri.getRawAuthority()==null || !uri.getRawAuthority().equalsIgnoreCase(host)
                || (uri.getPath()!=null && !uri.getPath().isEmpty()) || uri.getQuery()!=null || uri.getFragment()!=null)
                throw new ApiError(403,"Cross-origin writes are not permitted.");
        } catch (IllegalArgumentException e) { throw new ApiError(403,"Invalid request origin."); }
    }
    private static JsonObject readBody(HttpExchange exchange) throws IOException {
        String type=exchange.getRequestHeaders().getFirst("Content-Type");
        if (type==null || !type.toLowerCase(Locale.ROOT).startsWith("application/json")) throw new ApiError(400,"Use application/json for request bodies.");
        byte[] body=exchange.getRequestBody().readNBytes(MAX_BODY+1);
        if (body.length>MAX_BODY) throw new ApiError(413,"Request body is too large.");
        try {
            JsonReader reader=new JsonReader(new StringReader(new String(body,StandardCharsets.UTF_8)));
            reader.setStrictness(Strictness.STRICT);
            JsonElement value=JsonParser.parseReader(reader);
            if (!value.isJsonObject() || reader.peek()!=com.google.gson.stream.JsonToken.END_DOCUMENT) throw new ApiError(400,"Request body must be a JSON object.");
            return value.getAsJsonObject();
        } catch (JsonParseException | IllegalStateException | IOException e) { throw new ApiError(400,"Malformed JSON request body."); }
    }
    private Object saveMenu(JsonObject body,Long id,String accountId) throws SQLException {
        String name=text(body,"name",1,80);
        String category=text(body,"category",1,40);
        String description=body.has("description") ? text(body,"description",0,300) : "";
        String image=body.has("image") ? text(body,"image",0,500) : "";
        long price=integer(body,"price_paise",1,10000000);
        long stock=integer(body,"stock",0,1000000);
        int active=body.has("active") ? (int)integer(body,"active",0,1) : 1;
        synchronized(writeLock) {
            try(Connection c=connect()) {
                if(id==null) {
                    execute(c,"INSERT INTO menu_items(name,category,description,price_paise,stock,image,active,account_id) VALUES(?,?,?,?,?,?,?,?)",name,category,description,price,stock,image,active,accountId);
                    id=((Number)rows(c,"SELECT last_insert_rowid() AS id").get(0).get("id")).longValue();
                } else if(execute(c,"UPDATE menu_items SET name=?,category=?,description=?,price_paise=?,stock=?,image=?,active=? WHERE id=? AND account_id=?",name,category,description,price,stock,image,active,id,accountId)==0)
                    throw new ApiError(404,"Menu item not found.");
                return Map.of("item",rows(c,"SELECT * FROM menu_items WHERE id=? AND account_id=?",id,accountId).get(0));
            }
        }
    }
    private Object placeOrder(JsonObject body,String accountId) throws SQLException {
        String id=text(body,"id",36,36);
        if(!id.matches("(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) throw new ApiError(400,"Order ID must be a UUID.");
        String customer=text(body,"customer_name",1,80), type=text(body,"order_type",1,20), payment=text(body,"payment_method",1,20);
        if(!ORDER_TYPES.contains(type) || !PAYMENTS.contains(payment)) throw new ApiError(400,"Invalid order type or payment method.");
        JsonElement requested=body.get("items");
        if(requested==null || !requested.isJsonArray() || requested.getAsJsonArray().isEmpty() || requested.getAsJsonArray().size()>500)
            throw new ApiError(400,"Include between 1 and 500 item entries.");
        SortedMap<Long,Long> quantities=new TreeMap<>();
        for(JsonElement element:requested.getAsJsonArray()) {
            if(!element.isJsonObject()) throw new ApiError(400,"Each order item must be an object.");
            long itemId=integer(element.getAsJsonObject(),"item_id",1,Integer.MAX_VALUE);
            long quantity=integer(element.getAsJsonObject(),"quantity",1,10000);
            quantities.merge(itemId,quantity,Long::sum);
            if(quantities.get(itemId)>10000) throw new ApiError(400,"Quantity must not exceed 10000 per item.");
        }
        if(quantities.size()>50) throw new ApiError(400,"A maximum of 50 distinct items is allowed.");
        synchronized(writeLock) {
            try(Connection c=connect(); Statement tx=c.createStatement()) {
                // BEGIN IMMEDIATE acquires the SQLite writer lock before reading inventory.
                tx.execute("BEGIN IMMEDIATE");
                try {
                    Map<String,Object> existing=order(c,id,accountId);
                    if(existing!=null) {
                        boolean same=customer.equals(existing.get("customer_name")) && type.equals(existing.get("order_type")) && payment.equals(existing.get("payment_method"));
                        SortedMap<Long,Long> old=new TreeMap<>();
                        @SuppressWarnings("unchecked") List<Map<String,Object>> oldItems=(List<Map<String,Object>>)existing.get("items");
                        for(Map<String,Object> item:oldItems) old.put(((Number)item.get("item_id")).longValue(),((Number)item.get("quantity")).longValue());
                        if(!same || !old.equals(quantities)) throw new ApiError(409,"This order ID was already used for a different order.");
                        tx.execute("COMMIT");
                        return Map.of("order",existing);
                    }
                    if(!rows(c,"SELECT id FROM orders WHERE id=?",id).isEmpty())throw new ApiError(409,"This order ID is unavailable. Start a new order.");
                    List<Map<String,Object>> items=new ArrayList<>(); long total=0;
                    for(Map.Entry<Long,Long> q:quantities.entrySet()) {
                        List<Map<String,Object>> found=rows(c,"SELECT * FROM menu_items WHERE id=? AND active=1 AND account_id=?",q.getKey(),accountId);
                        if(found.isEmpty()) throw new ApiError(404,"A selected item is unavailable.");
                        Map<String,Object> m=found.get(0);
                        if(((Number)m.get("stock")).longValue()<q.getValue()) throw new ApiError(409,"Not enough stock for " + m.get("name") + ". Refresh the menu and try again.");
                        long price=((Number)m.get("price_paise")).longValue(); total += price*q.getValue();
                        items.add(Map.of("item_id",q.getKey(),"item_name",m.get("name"),"quantity",q.getValue(),"unit_price_paise",price));
                    }
                    execute(c,"INSERT INTO orders(id,customer_name,order_type,payment_method,created_at,total_paise,is_demo,account_id) VALUES(?,?,?,?,?,?,0,?)",id,customer,type,payment,Instant.now().toString(),total,accountId);
                    for(Map<String,Object> item:items) {
                        if(execute(c,"UPDATE menu_items SET stock=stock-? WHERE id=? AND stock>=? AND active=1 AND account_id=?",item.get("quantity"),item.get("item_id"),item.get("quantity"),accountId)!=1)
                            throw new ApiError(409,"Stock changed. Please refresh and try again.");
                        execute(c,"INSERT INTO order_items(order_id,item_id,item_name,quantity,unit_price_paise) VALUES(?,?,?,?,?)",id,item.get("item_id"),item.get("item_name"),item.get("quantity"),item.get("unit_price_paise"));
                    }
                    Map<String,Object> completed=order(c,id,accountId);
                    tx.execute("COMMIT");
                    return Map.of("order",completed);
                } catch(Exception e) {
                    try { tx.execute("ROLLBACK"); } catch(SQLException ignored) {}
                    throw e;
                }
            }
        }
    }
    private static Map<String,Object> order(Connection c,String id,String accountId) throws SQLException {
        List<Map<String,Object>> found=rows(c,"SELECT * FROM orders WHERE id=? AND account_id=?",id,accountId);
        if(found.isEmpty()) return null;
        Map<String,Object> order=found.get(0);
        order.put("items",rows(c,"SELECT item_id,item_name,quantity,unit_price_paise FROM order_items WHERE order_id=? ORDER BY item_id",id));
        return order;
    }
    private void serveFile(HttpExchange exchange,String path,boolean head) throws IOException {
        Path target;
        if(path.equals("/submission.zip")) { serveSubmission(exchange,head); return; }
        else {
            if(path.equals("/")) path="/index.html";
            Path web=root.resolve("web").toAbsolutePath().normalize();
            target=web.resolve(path.substring(1)).normalize();
            if(!target.startsWith(web)) throw new ApiError(404,"File not found.");
        }
        if(!Files.isRegularFile(target)) throw new ApiError(404,"File not found.");
        String name=target.getFileName().toString();
        String type=name.endsWith(".html") ? "text/html; charset=utf-8" : name.endsWith(".css") ? "text/css; charset=utf-8" : name.endsWith(".js") ? "text/javascript; charset=utf-8" : name.endsWith(".zip") ? "application/zip" : "application/octet-stream";
        exchange.getResponseHeaders().set("Content-Type",type);
        if(name.endsWith(".zip")) exchange.getResponseHeaders().set("Content-Disposition","attachment; filename=virudhigakv-canteen-submission.zip");
        if(head) exchange.sendResponseHeaders(200,-1);
        else { exchange.sendResponseHeaders(200,Files.size(target)); Files.copy(target,exchange.getResponseBody()); }
    }
    /** Package only authored project files and synthetic sample data; never runtime databases or credentials. */
    private void serveSubmission(HttpExchange exchange, boolean head) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", "application/zip");
        exchange.getResponseHeaders().set("Content-Disposition", "attachment; filename=virudhigakv-canteen-submission.zip");
        if (head) { exchange.sendResponseHeaders(200, -1); return; }
        Set<String> folders = Set.of("web", "server", "java", "database", "analysis", "docs", "samples", "tests", "scripts", "drizzle");
        Set<String> rootFiles = Set.of("README.md", "requirements.txt", "package.json", ".gitignore");
        Set<String> excluded = Set.of("lib", "build", "__pycache__", "node_modules", ".local", ".venv", "output", "outputs", ".pytest_cache");
        exchange.sendResponseHeaders(200, 0);
        try (ZipOutputStream zip = new ZipOutputStream(exchange.getResponseBody()); var files = Files.walk(root)) {
            zip.putNextEntry(new ZipEntry("virudhigakv-canteen/.openai/hosting.json"));
            zip.write("{\"d1\":\"DB\",\"r2\":null}\n".getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            for (Path file : files.filter(p -> Files.isRegularFile(p, LinkOption.NOFOLLOW_LINKS)).sorted().toList()) {
                Path relative = root.relativize(file);
                String name = relative.toString().replace(File.separatorChar, '/');
                if (!folders.contains(relative.getName(0).toString()) && !rootFiles.contains(name)) continue;
                boolean skip = false;
                for (Path part : relative) if (excluded.contains(part.toString())) skip = true;
                if (skip || name.endsWith(".pyc") || name.endsWith(".class") || name.endsWith(".jar") ||
                    ((name.endsWith(".db") || name.endsWith(".sqlite") || name.endsWith(".db-wal") || name.endsWith(".db-shm")) && !name.equals("samples/canteen-demo.db"))) continue;
                zip.putNextEntry(new ZipEntry("virudhigakv-canteen/" + name));
                Files.copy(file, zip);
                zip.closeEntry();
            }
        }
    }
    private static int execute(Connection c,String sql,Object... args) throws SQLException {
        try(PreparedStatement p=c.prepareStatement(sql)) { bind(p,args); return p.executeUpdate(); }
    }
    private static List<Map<String,Object>> rows(Connection c,String sql,Object... args) throws SQLException {
        try(PreparedStatement p=c.prepareStatement(sql)) {
            bind(p,args);
            try(ResultSet rs=p.executeQuery()) {
                List<Map<String,Object>> result=new ArrayList<>(); ResultSetMetaData meta=rs.getMetaData();
                while(rs.next()) { Map<String,Object> row=new LinkedHashMap<>(); for(int i=1;i<=meta.getColumnCount();i++) row.put(meta.getColumnLabel(i),rs.getObject(i)); result.add(row); }
                return result;
            }
        }
    }
    private static void bind(PreparedStatement statement,Object[] values) throws SQLException { for(int i=0;i<values.length;i++) statement.setObject(i+1,values[i]); }
    private static String text(JsonObject body,String key,int min,int max) {
        JsonElement value=body.get(key);
        if(value==null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) throw new ApiError(400,key + " must be text.");
        String s=value.getAsString().trim();
        if(s.length()<min || s.length()>max || s.chars().anyMatch(ch->ch<32)) throw new ApiError(400,key + " must contain " + min + "–" + max + " characters without control characters.");
        return s;
    }
    private static long integer(JsonObject body,String key,long min,long max) {
        JsonElement value=body.get(key);
        try {
            if(value==null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) throw new NumberFormatException();
            long n=value.getAsBigDecimal().longValueExact();
            if(n<min || n>max) throw new NumberFormatException();
            return n;
        } catch(ArithmeticException | NumberFormatException e) { throw new ApiError(400,key + " must be an integer between " + min + " and " + max + "."); }
    }
    private static String optional(JsonObject object,String key,String fallback) { return object.has(key) ? object.get(key).getAsString() : fallback; }
    private static void sendJson(HttpExchange exchange,int status,Object body) throws IOException {
        byte[] bytes=JSON.toJson(body).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type","application/json; charset=utf-8");
        exchange.sendResponseHeaders(status,bytes.length);
        exchange.getResponseBody().write(bytes);
    }
    private static final class ApiError extends RuntimeException {
        final int status;
        ApiError(int status,String message) { super(message); this.status=status; }
    }
}
