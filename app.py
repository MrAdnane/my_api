import hashlib, hmac, json, os, secrets, sqlite3, time
from functools import wraps
import jwt
from flask import Flask, jsonify, request

DB = os.getenv("DB_PATH", "earthquakes.db")
SECRET = os.getenv("JWT_SECRET", "change-me")
TOKEN_TTL = 3600
CACHE_TTL = 60

app = Flask(__name__)

# ---------- DB ----------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT UNIQUE, salt TEXT, pwd TEXT);
    CREATE TABLE IF NOT EXISTS earthquakes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, place TEXT, magnitude REAL,
        depth_km REAL, latitude REAL, longitude REAL, occurred_at TEXT);""")
    c.commit()
    c.close()
init_db()

# ---------- Cache (Redis, falls back to memory) ----------
try:
    import redis
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                             decode_responses=True, socket_connect_timeout=1)
    r.ping()
except Exception:
    r = None
_mem = {}

def cache_get(k):
    if r:
        return r.get(k)
    v = _mem.get(k)
    return v[1] if v and v[0] > time.time() else None

def cache_set(k, v):
    if r:
        r.setex(k, CACHE_TTL, v)
    else:
        _mem[k] = (time.time() + CACHE_TTL, v)

def cache_clear():
    if r:
        for k in r.scan_iter("eq:*"):
            r.delete(k)
    else:
        _mem.clear()

# ---------- Auth ----------
def hash_pwd(pwd, salt):
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 100000).hex()

def auth_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        h = request.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return jsonify(error="Missing token"), 401
        try:
            jwt.decode(h[7:], SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify(error="Invalid or expired token"), 401
        return f(*a, **kw)
    return wrapper

def creds():
    d = request.get_json(silent=True) or {}
    u, p = d.get("username", ""), d.get("password", "")
    if len(u) < 3 or len(p) < 6:
        return None, None
    return u, p

FIELDS = ["place", "magnitude", "depth_km", "latitude", "longitude", "occurred_at"]

def parse_eq():
    d = request.get_json(silent=True) or {}
    try:
        return (str(d["place"]), float(d["magnitude"]), float(d["depth_km"]),
                float(d["latitude"]), float(d["longitude"]), str(d["occurred_at"]))
    except (KeyError, ValueError, TypeError):
        return None

@app.route("/auth/register", methods=["POST"])
def register():
    u, p = creds()
    if not u:
        return jsonify(error="username >= 3 chars, password >= 6 chars"), 422
    salt = secrets.token_hex(8)
    try:
        c = db()
        c.execute("INSERT INTO users(username,salt,pwd) VALUES(?,?,?)", (u, salt, hash_pwd(p, salt)))
        c.commit()
        c.close()
    except sqlite3.IntegrityError:
        return jsonify(error="Username already exists"), 409
    return jsonify(message="User created"), 201

@app.route("/auth/login", methods=["POST"])
def login():
    u, p = creds()
    if not u:
        return jsonify(error="Bad credentials"), 401
    c = db()
    row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    c.close()
    if not row or not hmac.compare_digest(row["pwd"], hash_pwd(p, row["salt"])):
        return jsonify(error="Bad credentials"), 401
    token = jwt.encode({"sub": u, "exp": int(time.time()) + TOKEN_TTL}, SECRET, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode()
    return jsonify(access_token=token, token_type="bearer", expires_in=TOKEN_TTL)

# ---------- Earthquakes ----------
@app.route("/earthquakes", methods=["GET"])
def list_eq():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(20, max(1, int(request.args.get("per_page", 20))))
        mm = request.args.get("min_magnitude")
        mm = float(mm) if mm else None
    except ValueError:
        return jsonify(error="Invalid query parameter"), 422
    key = "eq:list:%s:%s:%s" % (page, per_page, mm)
    hit = cache_get(key)
    if hit:
        return jsonify(json.loads(hit))
    where, args = ("WHERE magnitude >= ?", [mm]) if mm is not None else ("", [])
    c = db()
    total = c.execute("SELECT COUNT(*) FROM earthquakes " + where, args).fetchone()[0]
    rows = c.execute("SELECT * FROM earthquakes %s ORDER BY id LIMIT ? OFFSET ?" % where,
                     args + [per_page, (page - 1) * per_page]).fetchall()
    c.close()
    out = {"page": page, "per_page": per_page, "total": total,
           "pages": -(-total // per_page), "data": [dict(x) for x in rows]}
    cache_set(key, json.dumps(out))
    return jsonify(out)

@app.route("/earthquakes/<int:eid>", methods=["GET"])
def get_eq(eid):
    key = "eq:one:%s" % eid
    hit = cache_get(key)
    if hit:
        return jsonify(json.loads(hit))
    c = db()
    row = c.execute("SELECT * FROM earthquakes WHERE id=?", (eid,)).fetchone()
    c.close()
    if not row:
        return jsonify(error="Not found"), 404
    cache_set(key, json.dumps(dict(row)))
    return jsonify(dict(row))

@app.route("/earthquakes", methods=["POST"])
@auth_required
def create_eq():
    v = parse_eq()
    if not v:
        return jsonify(error="Required: " + ", ".join(FIELDS)), 422
    c = db()
    cur = c.execute("INSERT INTO earthquakes(place,magnitude,depth_km,latitude,longitude,occurred_at) VALUES(?,?,?,?,?,?)", v)
    c.commit()
    new_id = cur.lastrowid
    c.close()
    cache_clear()
    return jsonify(dict(zip(["id"] + FIELDS, (new_id,) + v))), 201

@app.route("/earthquakes/<int:eid>", methods=["PUT"])
@auth_required
def update_eq(eid):
    v = parse_eq()
    if not v:
        return jsonify(error="Required: " + ", ".join(FIELDS)), 422
    c = db()
    cur = c.execute("UPDATE earthquakes SET place=?,magnitude=?,depth_km=?,latitude=?,longitude=?,occurred_at=? WHERE id=?", v + (eid,))
    c.commit()
    n = cur.rowcount
    c.close()
    if n == 0:
        return jsonify(error="Not found"), 404
    cache_clear()
    return jsonify(dict(zip(["id"] + FIELDS, (eid,) + v)))

@app.route("/earthquakes/<int:eid>", methods=["DELETE"])
@auth_required
def delete_eq(eid):
    c = db()
    cur = c.execute("DELETE FROM earthquakes WHERE id=?", (eid,))
    c.commit()
    n = cur.rowcount
    c.close()
    if n == 0:
        return jsonify(error="Not found"), 404
    cache_clear()
    return "", 204

# ---------- Swagger docs ----------
def _eq_schema():
    return {"type": "object", "properties": {
        "place": {"type": "string"}, "magnitude": {"type": "number"},
        "depth_km": {"type": "number"}, "latitude": {"type": "number"},
        "longitude": {"type": "number"}, "occurred_at": {"type": "string"}}}

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "My Api - Earthquakes", "version": "1.0"},
    "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
    "paths": {
        "/auth/register": {"post": {"summary": "Register", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}}}}}, "responses": {"201": {"description": "Created"}}}},
        "/auth/login": {"post": {"summary": "Login (returns token)", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}}}}}, "responses": {"200": {"description": "Token"}}}},
        "/earthquakes": {
            "get": {"summary": "List (paginated, max 20)", "parameters": [
                {"name": "page", "in": "query", "schema": {"type": "integer"}},
                {"name": "per_page", "in": "query", "schema": {"type": "integer", "maximum": 20}},
                {"name": "min_magnitude", "in": "query", "schema": {"type": "number"}}],
                "responses": {"200": {"description": "OK"}}},
            "post": {"summary": "Create", "security": [{"bearer": []}], "requestBody": {"content": {"application/json": {"schema": _eq_schema()}}}, "responses": {"201": {"description": "Created"}}}},
        "/earthquakes/{id}": {
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "get": {"summary": "Get one", "responses": {"200": {"description": "OK"}}},
            "put": {"summary": "Update", "security": [{"bearer": []}], "requestBody": {"content": {"application/json": {"schema": _eq_schema()}}}, "responses": {"200": {"description": "OK"}}},
            "delete": {"summary": "Delete", "security": [{"bearer": []}], "responses": {"204": {"description": "Deleted"}}}},
    },
}

@app.route("/openapi.json")
def openapi():
    return jsonify(SPEC)

@app.route("/docs")
def docs():
    return """<!doctype html><html><head><title>My Api docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#ui'})</script></body></html>"""

if __name__ == "__main__":
    app.run(port=8000)
