"""Minimal stand-in for Supabase Auth (GoTrue) + PostgREST, enough for Speicherpunkt tests."""
import json, uuid, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

KEY = "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l"

class Store:
    def __init__(self):
        self.users = {}      # email -> {id, password}
        self.tokens = {}     # access -> (uid, exp)
        self.refresh = {}    # refresh -> uid
        self.rows = {}       # uid -> {data, updated_at}
        self.down = False
        self.expires_in = 3600
        self.calls = []
        self.suggest_bodies = []
        self.suggest_status = 200
        self.recover = []
        self.waitlist = []
        self.waitlist_status = 0
        self.lock = threading.Lock()

S = Store()

def session_for(uid, email):
    a, r = secrets.token_hex(16), secrets.token_hex(16)
    S.tokens[a] = (uid, time.time() + S.expires_in); S.refresh[r] = uid
    return {"access_token": a, "refresh_token": r, "expires_in": S.expires_in, "token_type": "bearer",
            "user": {"id": uid, "email": email}}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "apikey, authorization, content-type, prefer")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
    def reply(self, code, obj=None):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code); self.cors()
        if obj is not None: self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self.send_response(204); self.cors(); self.send_header("Content-Length", "0"); self.end_headers()
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n) or b"{}")
    def uid(self):
        a = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        t = S.tokens.get(a)
        if not t or t[1] < time.time(): return None
        return t[0]
    def guard(self):
        if S.down: self.connection.close(); return False
        if self.headers.get("apikey") != KEY: self.reply(401, {"message": "Invalid API key"}); return False
        return True
    def do_GET(self):
        if not self.guard(): return
        u = urlparse(self.path); S.calls.append(("GET", u.path))
        if u.path == "/rest/v1/sp_state":
            uid = self.uid()
            if not uid: return self.reply(401, {"message": "JWT expired", "code": "PGRST301"})
            row = S.rows.get(uid)
            return self.reply(200, [row] if row else [])
        if u.path == "/auth/v1/user":
            uid = self.uid()
            if not uid: return self.reply(401, {"msg": "invalid JWT"})
            email = next(k for k, v in S.users.items() if v["id"] == uid)
            return self.reply(200, {"id": uid, "email": email})
        self.reply(404, {"message": "not found"})
    def do_PUT(self):
        if not self.guard(): return
        u = urlparse(self.path); S.calls.append(("PUT", u.path)); b = self.body()
        if u.path == "/auth/v1/user":
            uid = self.uid()
            if not uid: return self.reply(401, {"msg": "invalid JWT"})
            email = next(k for k, v in S.users.items() if v["id"] == uid)
            if "password" in b:
                if len(b["password"]) < 6: return self.reply(422, {"error_code": "weak_password", "msg": "Password should be at least 6 characters."})
                if b["password"] == S.users[email]["password"]: return self.reply(422, {"error_code": "same_password", "msg": "New password should be different from the old password."})
                S.users[email]["password"] = b["password"]
            return self.reply(200, {"id": uid, "email": email})
        self.reply(404, {"message": "not found"})
    def do_POST(self):
        if not self.guard(): return
        u = urlparse(self.path); q = parse_qs(u.query); S.calls.append(("POST", u.path + "?" + u.query))
        b = self.body()
        with S.lock:
            if u.path == "/auth/v1/signup":
                e = b.get("email", "").lower()
                if len(b.get("password", "")) < 6: return self.reply(422, {"code": 422, "error_code": "weak_password", "msg": "Password should be at least 6 characters."})
                if e in S.users: return self.reply(422, {"code": 422, "error_code": "user_already_exists", "msg": "User already registered"})
                S.users[e] = {"id": str(uuid.uuid4()), "password": b["password"]}
                return self.reply(200, session_for(S.users[e]["id"], e))
            if u.path == "/auth/v1/token":
                gt = q.get("grant_type", [""])[0]
                if gt == "password":
                    e = b.get("email", "").lower(); usr = S.users.get(e)
                    if not usr or usr["password"] != b.get("password"): return self.reply(400, {"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"})
                    return self.reply(200, session_for(usr["id"], e))
                if gt == "refresh_token":
                    uid = S.refresh.pop(b.get("refresh_token"), None)
                    if not uid: return self.reply(400, {"error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"})
                    email = next(k for k, v in S.users.items() if v["id"] == uid)
                    return self.reply(200, session_for(uid, email))
            if u.path == "/functions/v1/suggest-step":
                uid = self.uid()
                if not uid: return self.reply(401, {"error": "signed_out"})
                S.suggest_bodies.append(b)
                if S.suggest_status != 200: return self.reply(S.suggest_status, {"error": "x"})
                base = b.get("step") or b.get("project") or "Projekt"
                return self.reply(200, {"suggestions": [
                    {"step": "KI-Mini: " + base[:30], "minutes": 2},
                    {"step": "KI-Weiter (" + b.get("mode", "?") + ")", "minutes": 10},
                    {"step": "KI-Anders mit Timer", "minutes": 5}]})
            if u.path == "/rest/v1/sp_waitlist":
                if S.waitlist_status: return self.reply(S.waitlist_status, {"message": "x"})
                e = str(b.get("email", ""))
                if "@" not in e or len(e) < 6: return self.reply(400, {"code": "23514", "message": "check constraint"})
                if any(w["email"].lower() == e.lower() for w in S.waitlist): return self.reply(409, {"code": "23505", "message": "duplicate key"})
                S.waitlist.append({"email": e, "note": b.get("note"), "source": b.get("source")})
                return self.reply(201)
            if u.path == "/rest/v1/rpc/sp_delete_account":
                uid = self.uid()
                if not uid: return self.reply(401, {"message": "JWT expired"})
                email = next(k for k, v in S.users.items() if v["id"] == uid)
                del S.users[email]; S.rows.pop(uid, None)
                for k in [k for k, v in S.tokens.items() if v[0] == uid]: del S.tokens[k]
                return self.reply(204)
            if u.path == "/auth/v1/recover":
                S.recover.append({"email": b.get("email"), "redirect_to": q.get("redirect_to", [""])[0]})
                return self.reply(200, {})
            if u.path == "/auth/v1/logout":
                return self.reply(204)
            if u.path == "/rest/v1/sp_state":
                uid = self.uid()
                if not uid: return self.reply(401, {"message": "JWT expired", "code": "PGRST301"})
                if b.get("user_id") != uid: return self.reply(403, {"message": "new row violates row-level security policy", "code": "42501"})
                S.rows[uid] = {"data": b["data"], "updated_at": b.get("updated_at", 0)}
                return self.reply(201)
        self.reply(404, {"message": "not found"})

def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, S
