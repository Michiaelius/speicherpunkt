"""Ein kleines, echtes Supabase zum Testen: Postgres + PostgREST (dieselbe Software wie bei Supabase)
plus ein Ersatz für Anmeldung (GoTrue) und Gateway.

Braucht: Postgres 15 oder neuer (initdb, pg_ctl, psql) und PostgREST 12 (Umgebungsvariable POSTGREST
oder im PATH). Fehlt etwas, meldet available() den Grund und die Tests werden übersprungen.
"""
import os, shutil, subprocess, tempfile, time, json, hmac, hashlib, base64, secrets, threading, socket, pathlib
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

KEY = "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l"
JWT_SECRET = "lokaler-test-schluessel-mit-mindestens-32-zeichen"
HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent.parent


def _pg_bin(name):
    cands = [os.environ.get("PG_BIN", "")] + sorted((str(p) for p in pathlib.Path("/usr/lib/postgresql").glob("*/bin")), reverse=True)
    for d in cands:
        if d and (pathlib.Path(d) / name).exists(): return str(pathlib.Path(d) / name)
    return shutil.which(name)


def available():
    missing = [n for n in ("initdb", "pg_ctl", "psql", "postgres") if not _pg_bin(n)]
    if missing: return False, "Postgres fehlt (" + ", ".join(missing) + ")"
    if not (os.environ.get("POSTGREST") or shutil.which("postgrest")): return False, "PostgREST fehlt (Umgebungsvariable POSTGREST setzen)"
    return True, ""


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt(payload):
    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()); p = b64(json.dumps(payload).encode())
    sig = b64(hmac.new(JWT_SECRET.encode(), (h + "." + p).encode(), hashlib.sha256).digest())
    return h + "." + p + "." + sig


def jwt_sub(token):
    try:
        h, p, s = token.split(".")
        if not hmac.compare_digest(s, b64(hmac.new(JWT_SECRET.encode(), (h + "." + p).encode(), hashlib.sha256).digest())): return None
        d = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        return d["sub"] if d.get("exp", 0) > time.time() else None
    except Exception:
        return None


class Local:
    def __init__(self, workdir=None):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sp-lokal-", dir=workdir))
        self.procs = []
        self.users = {}           # email -> {id, password}
        self.refresh = {}         # refresh -> (uid, email)
        self.after_state_get = None   # Testhaken: läuft nach dem Lesen von sp_state, bevor die App die Antwort bekommt (z. B. ein zweites Gerät schreibt)
        self.calls = []
        self.expires_in = 3600

    # ---------- Postgres ----------
    def _as_user(self, cmd):
        if os.geteuid() == 0:   # Postgres läuft nicht als root
            user = os.environ.get("PG_RUN_AS", "nobody")
            return ["runuser", "-u", user, "--"] + cmd
        return cmd

    def psql(self, sql, db="postgres"):
        r = subprocess.run([_pg_bin("psql"), "-h", str(self.tmp), "-p", str(self.pg_port), "-U", "postgres", "-d", db,
                            "-v", "ON_ERROR_STOP=1", "-qAt", "-c", sql], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr)
        return r.stdout.strip()

    def psql_file(self, path):
        r = subprocess.run([_pg_bin("psql"), "-h", str(self.tmp), "-p", str(self.pg_port), "-U", "postgres", "-d", "postgres",
                            "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr)

    def start(self):
        if os.geteuid() == 0: shutil.chown(self.tmp, os.environ.get("PG_RUN_AS", "nobody"))
        self.pg_port = free_port()
        subprocess.run(self._as_user([_pg_bin("initdb"), "-D", str(self.tmp / "data"), "-U", "postgres", "-A", "trust", "--no-sync"]),
                       check=True, capture_output=True)
        subprocess.run(self._as_user([_pg_bin("pg_ctl"), "-D", str(self.tmp / "data"), "-w", "-l", str(self.tmp / "pg.log"),
                                      "-o", f"-p {self.pg_port} -k {self.tmp} -c listen_addresses=127.0.0.1 -c fsync=off", "start"]),
                       check=True, capture_output=True)
        self.psql_file(HERE / "supabase_stub.sql")
        self.psql_file(APP / "supabase-setup.sql")
        # PostgREST
        self.rest_port = free_port()
        env = dict(os.environ, PGRST_DB_URI=f"postgres://authenticator@127.0.0.1:{self.pg_port}/postgres", PGRST_DB_SCHEMAS="public",
                   PGRST_DB_ANON_ROLE="anon", PGRST_JWT_SECRET=JWT_SECRET, PGRST_SERVER_PORT=str(self.rest_port),
                   PGRST_SERVER_HOST="127.0.0.1", PGRST_DB_CHANNEL_ENABLED="true", PGRST_LOG_LEVEL="crit")
        self.procs.append(subprocess.Popen([os.environ.get("POSTGREST") or shutil.which("postgrest")], env=env,
                                           stdout=open(self.tmp / "postgrest.log", "w"), stderr=subprocess.STDOUT))
        self._wait(f"http://127.0.0.1:{self.rest_port}/", "PostgREST")
        # Gateway
        self.gw = ThreadingHTTPServer(("127.0.0.1", 0), _gateway(self))
        threading.Thread(target=self.gw.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.gw.server_address[1]}"
        return self

    def _wait(self, url, name, ok_codes=(200,)):
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1); return
            except urllib.error.HTTPError as e:
                if e.code in ok_codes: return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError(name + " startet nicht")

    def reload_schema(self):
        self.psql("notify pgrst, 'reload schema'"); time.sleep(0.8)

    def stop(self):
        for p in self.procs:
            p.terminate()
            try: p.wait(5)
            except Exception: p.kill()
        try: self.gw.shutdown()
        except Exception: pass
        subprocess.run(self._as_user([_pg_bin("pg_ctl"), "-D", str(self.tmp / "data"), "-m", "immediate", "stop"]), capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- Anmeldung (Ersatz für GoTrue) ----------
    def session(self, uid, email):
        r = secrets.token_hex(16); self.refresh[r] = (uid, email)
        a = jwt({"sub": uid, "role": "authenticated", "aud": "authenticated", "email": email,
                 "iat": int(time.time()), "exp": int(time.time()) + self.expires_in})
        return {"access_token": a, "refresh_token": r, "expires_in": self.expires_in, "token_type": "bearer", "user": {"id": uid, "email": email}}

    def signup(self, email, password):
        uid = self.psql("insert into auth.users (email) values ('%s') returning id" % email.replace("'", "''"))
        self.users[email] = {"id": uid, "password": password}
        return self.session(uid, email)


def _gateway(L):
    class G(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass

        def cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "apikey, authorization, content-type, prefer, x-client-info, accept")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "retry-after, content-range")

        def reply(self, code, obj=None, raw=None, headers=None):
            body = raw if raw is not None else (b"" if obj is None else json.dumps(obj).encode())
            self.send_response(code); self.cors()
            for k, v in (headers or {}).items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection", "access-control-allow-origin", "date", "server"): self.send_header(k, v)
            if obj is not None and raw is None: self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204); self.cors(); self.send_header("Content-Length", "0"); self.end_headers()

        def body(self):
            n = int(self.headers.get("Content-Length") or 0); return self.rfile.read(n) if n else b""

        def forward(self, target, data):
            hdrs = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type", "prefer", "accept", "content-profile", "accept-profile")}
            req = urllib.request.Request(target, data=data if self.command not in ("GET", "HEAD") else None, method=self.command, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read(), dict(e.headers)

        def handle_any(self):
            u = urlparse(self.path); data = self.body()
            L.calls.append((self.command, u.path))
            if self.headers.get("apikey") != KEY: return self.reply(401, {"message": "Invalid API key"})
            if u.path.startswith("/rest/v1/"):
                st, raw, h = self.forward(f"http://127.0.0.1:{L.rest_port}" + self.path[len("/rest/v1"):], data)
                if self.command == "GET" and u.path == "/rest/v1/sp_state" and L.after_state_get:
                    f, L.after_state_get = L.after_state_get, None; f()
                return self.reply(st, raw=raw, headers=h)
            if u.path.startswith("/auth/v1/"): return self.auth(u, json.loads(data or b"{}"))
            self.reply(404, {"message": "not found"})

        def auth(self, u, b):
            q = parse_qs(u.query); p = u.path
            if p == "/auth/v1/signup":
                e = b.get("email", "").lower()
                if len(b.get("password", "")) < 6: return self.reply(422, {"error_code": "weak_password", "msg": "Password should be at least 6 characters."})
                if e in L.users: return self.reply(422, {"error_code": "user_already_exists", "msg": "User already registered"})
                return self.reply(200, L.signup(e, b["password"]))
            if p == "/auth/v1/token":
                gt = q.get("grant_type", [""])[0]
                if gt == "password":
                    e = b.get("email", "").lower(); usr = L.users.get(e)
                    if not usr or usr["password"] != b.get("password"): return self.reply(400, {"error_code": "invalid_credentials", "msg": "Invalid login credentials"})
                    return self.reply(200, L.session(usr["id"], e))
                if gt == "refresh_token":
                    t = L.refresh.pop(b.get("refresh_token"), None)
                    if not t: return self.reply(400, {"error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"})
                    return self.reply(200, L.session(*t))
            if p == "/auth/v1/user":
                uid = jwt_sub((self.headers.get("Authorization") or "").replace("Bearer ", ""))
                if not uid: return self.reply(401, {"msg": "invalid JWT"})
                email = next((k for k, v in L.users.items() if v["id"] == uid), "")
                return self.reply(200, {"id": uid, "email": email})
            if p == "/auth/v1/logout": return self.reply(204)
            self.reply(404, {"message": "not found"})

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = handle_any
    return G
