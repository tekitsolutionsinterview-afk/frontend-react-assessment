
import os, json, secrets, hashlib, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMeNow!")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-this-admin-secret")

# Lightweight DB abstraction: PostgreSQL in Render, SQLite locally.
if DB_URL:
    import psycopg
    from psycopg.rows import dict_row
    def db():
        return psycopg.connect(DB_URL, row_factory=dict_row)
    PH = "%s"
else:
    import sqlite3
    DB_FILE = BASE / "assessment.db"
    def db():
        c = sqlite3.connect(DB_FILE)
        c.row_factory = sqlite3.Row
        return c
    PH = "?"

SESSIONS_TABLE = "react_sessions"

app = FastAPI(title="React Frontend Assessment Platform", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

QUESTIONS = [
("q1","JavaScript Event Loop","Explain how the event loop handles a synchronous loop, Promise.then(), queueMicrotask(), setTimeout(...,0), and requestAnimationFrame(). Give the execution order and explain why."),
("q2","Closures & Loops","A loop creates callbacks that should print 0,1,2,3,4 but all callbacks print 5. Explain the closure issue and give two correct fixes without using a global variable."),
("q3","this / bind / arrows","Compare this behavior in a normal function, arrow function, object method, and callback passed to setTimeout. Explain bind(), call(), and apply() with a practical example."),
("q4","Prototype & equality","Explain the prototype chain and the difference between Object.create(), class syntax, instanceof, ===, Object.is(), and shallow equality. Identify one React bug these differences can cause."),
("q5","Async cancellation","Design a search-as-you-type request flow that prevents stale responses from overwriting newer results. Compare AbortController with request IDs and explain cleanup."),
("q6","React rendering","Explain what causes a React component to re-render. Discuss state identity, parent renders, props, context, React.memo and referential equality. Include one example of an unnecessary render."),
("q7","useEffect","Explain why an effect can repeatedly fire or use stale values. Give correct dependency-array rules and explain cleanup for subscriptions, timers, and fetch requests."),
("q8","Keys & reconciliation","Why are array indexes risky as React keys when items can be inserted, deleted or reordered? Explain reconciliation and give a concrete UI bug caused by unstable keys."),
("q9","State architecture","For a medium React app, decide what belongs in local state, Context, Redux/Zustand, URL state, and server/cache state. Explain why duplicating server state in multiple stores is dangerous."),
("q10","Forms","Compare controlled and uncontrolled inputs. Design a form with validation, async submit, disabled/loading state, server errors and prevention of duplicate submissions."),
("q11","REST integration","Design a robust React REST integration layer for GET/POST/PUT/DELETE. Cover loading, empty, error, retry, cancellation, authentication, response validation and optimistic updates."),
("q12","Web security","Explain XSS, CSRF, CORS and clickjacking. Which attacks are reduced by HttpOnly/SameSite cookies, CSP and frame-ancestors? Give secure frontend practices."),
("q13","Auth tokens","Compare storing access tokens in localStorage, sessionStorage, memory and HttpOnly cookies. Explain XSS/CSRF trade-offs and propose a safer browser authentication approach."),
("q14","CSS layout","Explain CSS specificity, stacking contexts and z-index. A modal appears behind a transformed card even with z-index:9999. Diagnose the cause and propose a fix."),
("q15","Responsive UI","Build a responsive dashboard strategy using CSS Grid/Flexbox, fluid sizing, media queries and mobile-first breakpoints. Explain how you would avoid layout shift."),
("q16","Accessibility","How would you make a custom modal, dropdown and icon button accessible? Cover semantic HTML, keyboard navigation, focus management, ARIA and screen-reader behavior."),
("q17","Performance","A React page renders 5,000 rows and typing in a filter feels slow. Give a prioritized optimization plan using profiling, memoization, virtualization, debouncing and data normalization."),
("q18","Testing","Explain how you would test a React form and API-driven component using React Testing Library. What should be tested from the user's perspective and what should not be implementation-detail tested?"),
("q19","Git & delivery","Describe a safe feature workflow using Git branches, commits, pull requests, review, conflict resolution and rollback. Explain how you would handle a broken production frontend release."),
("q20","Frontend architecture","Design the architecture of a production React/Next.js application with feature modules, shared UI, API layer, authentication, error boundaries, observability and environment configuration.")
]

CODING_PROMPT = """Implement a JavaScript debounce(fn, wait, options) utility.

Requirements:
1. Return a function that delays invocation until wait milliseconds have elapsed since the last call.
2. Preserve the latest this context and arguments.
3. Support options.leading and options.trailing.
4. Return the result of the most recent synchronous invocation when possible.
5. Expose cancel() and flush() methods.
6. Repeated calls must not create multiple active timers.
7. Explain any edge cases in comments.
Do not use external libraries."""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    c = db()
    if DB_URL:
        c.execute("""CREATE TABLE IF NOT EXISTS react_sessions(
            id BIGSERIAL PRIMARY KEY,
            candidate_name TEXT NOT NULL,
            email TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            answers JSONB DEFAULT '{}'::jsonb,
            code TEXT DEFAULT '',
            coding_tests JSONB DEFAULT '{}'::jsonb,
            started_at TEXT,
            submitted_at TEXT,
            score INTEGER DEFAULT 0,
            events JSONB DEFAULT '[]'::jsonb,
            proctor_events JSONB DEFAULT '[]'::jsonb,
            violation_count INTEGER DEFAULT 0,
            camera_granted BOOLEAN DEFAULT FALSE,
            created_at TEXT NOT NULL
        )""")
    else:
        c.execute("""CREATE TABLE IF NOT EXISTS react_sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_name TEXT NOT NULL,
            email TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            answers TEXT DEFAULT '{}',
            code TEXT DEFAULT '',
            coding_tests TEXT DEFAULT '{}',
            started_at TEXT,
            submitted_at TEXT,
            score INTEGER DEFAULT 0,
            events TEXT DEFAULT '[]',
            proctor_events TEXT DEFAULT '[]',
            violation_count INTEGER DEFAULT 0,
            camera_granted INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
    # Safe additive migration for databases created by earlier versions.
    migrations = [
        ("proctor_events", "JSONB DEFAULT '[]'::jsonb" if DB_URL else "TEXT DEFAULT '[]'"),
        ("violation_count", "INTEGER DEFAULT 0"),
        ("camera_granted", "BOOLEAN DEFAULT FALSE" if DB_URL else "INTEGER DEFAULT 0"),
        ("login_used_at", "TEXT"),
    ]
    for col, typ in migrations:
        try:
            c.execute(f"ALTER TABLE react_sessions ADD COLUMN IF NOT EXISTS {col} {typ}")
        except Exception:
            # SQLite versions without IF NOT EXISTS on ADD COLUMN are handled below.
            try:
                c.execute(f"ALTER TABLE react_sessions ADD COLUMN {col} {typ}")
            except Exception:
                pass
    c.commit(); c.close()

def ph_json(x):
    return json.dumps(x)

def rowdict(r):
    if hasattr(r, "keys"): return dict(r)
    return r

def get_session(token):
    c=db(); r=c.execute(f"SELECT * FROM react_sessions WHERE token={PH}", (token,)).fetchone(); c.close()
    if not r: raise HTTPException(404,"Assessment not found")
    return rowdict(r)

def hash_pw(p):
    return hashlib.sha256((ADMIN_SECRET + p).encode()).hexdigest()

def admin_ok(req: Request):
    return req.cookies.get("admin_session") == hashlib.sha256(ADMIN_SECRET.encode()).hexdigest()

def require_admin(req):
    if not admin_ok(req): raise HTTPException(401,"Admin authentication required")

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok","platform":"react-frontend-assessment"}

@app.get("/")
def home(): return FileResponse(STATIC/"assessment.html")

@app.get("/admin")
def admin(): return FileResponse(STATIC/"admin.html")

@app.post("/api/admin/login")
async def admin_login(req: Request, response: Response):
    data=await req.json()
    if secrets.compare_digest(str(data.get("password","")), ADMIN_PASSWORD):
        response.set_cookie("admin_session", hashlib.sha256(ADMIN_SECRET.encode()).hexdigest(),
                            httponly=True, secure=req.url.scheme=="https", samesite="strict", max_age=28800)
        return {"ok":True}
    raise HTTPException(401,"Invalid admin password")

@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie("admin_session")
    return {"ok":True}

@app.get("/api/admin/auth")
def admin_auth(req: Request): return {"authenticated":admin_ok(req)}

@app.post("/api/admin/create")
async def create_candidate(req: Request):
    require_admin(req); d=await req.json()
    name=str(d.get("name","")).strip(); email=str(d.get("email","")).strip()
    if not name or not email: raise HTTPException(400,"Name and email are required")
    login="REACT-"+secrets.token_hex(4).upper()
    pwd=secrets.token_urlsafe(6)
    token=secrets.token_urlsafe(18)
    c=db()
    vals=(name,email,login,hash_pw(pwd),token,ph_json({}),"",ph_json({}),ph_json([]),ph_json([]),0,False,now_iso())
    c.execute(f"""INSERT INTO react_sessions(candidate_name,email,login,password_hash,token,answers,code,coding_tests,events,proctor_events,violation_count,camera_granted,created_at)
                  VALUES ({','.join([PH]*13)})""", vals)
    c.commit(); c.close()
    return {"login":login,"password":pwd,"token":token}

@app.get("/api/admin/sessions")
def admin_sessions(req: Request):
    require_admin(req); c=db()
    rows=c.execute("SELECT id,candidate_name,email,login,token,started_at,submitted_at,score,created_at FROM react_sessions ORDER BY id DESC").fetchall()
    c.close(); return [rowdict(x) for x in rows]

@app.get("/api/admin/session/{token}")
def admin_detail(token: str, req: Request):
    require_admin(req); r=get_session(token)
    for k in ("answers","coding_tests","events","proctor_events"):
        if isinstance(r.get(k),str):
            try:r[k]=json.loads(r[k])
            except: r[k]={}
    return r

@app.post("/api/candidate/login")
async def candidate_login(req: Request):
    d=await req.json(); login=str(d.get("login","")).strip(); password=str(d.get("password",""))
    c=db()
    try:
        if DB_URL:
            c.execute("BEGIN")
            r=c.execute(f"SELECT * FROM react_sessions WHERE login={PH} FOR UPDATE",(login,)).fetchone()
        else:
            c.execute("BEGIN IMMEDIATE")
            r=c.execute(f"SELECT * FROM react_sessions WHERE login={PH}",(login,)).fetchone()
        r = rowdict(r) if r else None
        if not r or not secrets.compare_digest(hash_pw(password),r["password_hash"]):
            c.rollback(); raise HTTPException(401,"Invalid candidate credentials")
        if r["submitted_at"]:
            c.rollback(); raise HTTPException(409,"You have already taken the test")
        if r.get("login_used_at"):
            c.rollback(); raise HTTPException(409,"You have already taken the test")
        used=now_iso()
        c.execute(f"UPDATE react_sessions SET login_used_at={PH} WHERE id={PH}",(used,r["id"]))
        c.commit()
        return {"token":r["token"],"name":r["candidate_name"],"started_at":r["started_at"],"login_used_at":used}
    finally:
        c.close()

@app.post("/api/candidate/start/{token}")
async def start(token:str, req:Request):
    r=get_session(token)
    if r["submitted_at"]: raise HTTPException(409,"Assessment already submitted")
    data=await req.json() if req.headers.get("content-type","").startswith("application/json") else {}
    if not bool(data.get("camera_granted")):
        raise HTTPException(400,"Camera permission is required before starting the assessment")
    if not r["started_at"]:
        started=now_iso(); c=db(); c.execute(f"UPDATE react_sessions SET started_at={PH},camera_granted={PH} WHERE token={PH}",(started,True,token)); c.commit(); c.close()
        return {"started_at":started,"duration_seconds":2700}
    c=db(); c.execute(f"UPDATE react_sessions SET camera_granted={PH} WHERE token={PH}",(True,token)); c.commit(); c.close()
    return {"started_at":r["started_at"],"duration_seconds":2700}

@app.post("/api/proctor-event")
async def proctor_event(req:Request):
    d=await req.json(); token=d.get("token"); r=get_session(token)
    if r["submitted_at"]: return {"ok":False,"submitted":True}
    event={"type":str(d.get("type","unknown"))[:80],"detail":str(d.get("detail",""))[:300],"at":now_iso()}
    existing=r.get("proctor_events") or []
    if isinstance(existing,str):
        try: existing=json.loads(existing)
        except: existing=[]
    existing=(existing if isinstance(existing,list) else [])[-199:]+[event]
    violations=int(r.get("violation_count") or 0)+(1 if event["type"] in {"tab_switch","window_blur","fullscreen_exit","camera_revoked","copy_attempt","paste_attempt","cut_attempt","devtools_shortcut"} else 0)
    c=db(); c.execute(f"UPDATE react_sessions SET proctor_events={PH},violation_count={PH} WHERE token={PH}",(ph_json(existing),violations,token)); c.commit(); c.close()
    return {"ok":True,"violation_count":violations,"auto_submit":violations>=3}

@app.post("/api/autosave")
async def autosave(req:Request):
    d=await req.json(); token=d.get("token"); r=get_session(token)
    if r["submitted_at"]: return {"ok":False,"submitted":True}
    answers=d.get("answers",{}); code=d.get("code",""); events=d.get("events",[]); proctor=d.get("proctor_events",[])
    c=db()
    c.execute(f"UPDATE react_sessions SET answers={PH},code={PH},events={PH},proctor_events={PH} WHERE token={PH}",
              (ph_json(answers),code,ph_json(events[-200:]),ph_json(proctor[-200:]),token))
    c.commit(); c.close(); return {"ok":True}

def score_answer(text):
    t=(text or "").lower()
    if not t.strip(): return 0
    concepts = [
        ["event loop","microtask","macrotask"],["closure","let","scope"],["this","bind","arrow"],
        ["prototype","instanceof"],["abortcontroller","stale","cancel"],["render","memo","referential"],
        ["effect","dependency","cleanup"],["key","reconciliation"],["context","server state"],
        ["controlled","validation"],["loading","error","cancel"],["xss","csrf","cors"],
        ["httponly","localstorage","cookie"],["specificity","stacking","z-index"],["grid","flex","media"],
        ["aria","focus","keyboard"],["profil","virtual","deboun"],["testing library","user","mock"],
        ["branch","pull request","rollback"],["architecture","error boundary","observability"]
    ]
    return min(5, sum(1 for k in concepts[len([]):] if False))  # replaced below

def analyze_code(code):
    t=(code or "").lower()
    checks={
        "uses_timer": "settimeout" in t,
        "clears_timer": "cleartimeout" in t,
        "preserves_context": "this" in t,
        "preserves_arguments": "arguments" in t or "...args" in t,
        "leading_trailing": "leading" in t and "trailing" in t,
        "cancel_method": ".cancel" in t or "cancel =" in t,
        "flush_method": ".flush" in t or "flush =" in t,
        "single_timer_logic": t.count("settimeout") <= 3 and ("timer" in t or "timeout" in t),
    }
    return checks

def compute_score(answers, code, tests):
    keywords = [
      ["event loop","microtask","settimeout"],["closure","let","scope"],["this","bind","arrow"],
      ["prototype","instanceof"],["abortcontroller","stale"],["render","memo","referential"],
      ["effect","dependency","cleanup"],["key","reconciliation"],["context","server state"],
      ["controlled","validation"],["loading","error","cancel"],["xss","csrf","cors"],
      ["httponly","cookie","localstorage"],["specificity","stacking","z-index"],["grid","flex","media"],
      ["aria","focus","keyboard"],["profil","virtualization","debounce"],["testing library","user"],
      ["branch","pull request","rollback"],["architecture","error boundary","observability"]
    ]
    qscore=0
    for i in range(20):
        t=str(answers.get(f"q{i+1}","")).lower()
        if not t.strip(): continue
        hits=sum(1 for k in keywords[i] if k in t)
        qscore += min(4, hits) + (1 if len(t.split())>=45 else 0)
    qscore=min(90,qscore)
    # Coding score is question-specific: 8 browser execution checks + 2 source checks.
    passed=int((tests or {}).get("test_pass",0) or 0)
    static=analyze_code(code)
    static_points=sum(1 for k in ("uses_timer","clears_timer","preserves_context","preserves_arguments","leading_trailing","cancel_method","flush_method","single_timer_logic") if static[k])
    return min(90,qscore)+min(8,passed)+min(2,static_points//4), static

@app.post("/api/submit")
async def submit(req:Request):
    d=await req.json(); token=d.get("token"); r=get_session(token)
    if r["submitted_at"]: raise HTTPException(409,"Assessment already submitted")
    if not r["started_at"]: raise HTTPException(400,"Assessment has not started")
    elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(r["started_at"].replace("Z","+00:00"))).total_seconds()
    if elapsed > 2710: raise HTTPException(409,"Assessment time expired")
    answers=d.get("answers",{}); code=d.get("code",""); tests=d.get("coding_tests",{})
    missing=[f"Q{i}" for i in range(1,21) if not str(answers.get(f"q{i}","")).strip()]
    if missing and not d.get("auto_submit"):
        raise HTTPException(400,"Please answer all mandatory questions before submitting")
    if not code.strip() and not d.get("auto_submit"):
        raise HTTPException(400,"Coding solution is mandatory")
    score,static_analysis=compute_score(answers,code,tests)
    tests=dict(tests or {}); tests["server_static"]=static_analysis
    c=db(); c.execute(f"""UPDATE react_sessions SET answers={PH},code={PH},coding_tests={PH},
             score={PH},submitted_at={PH} WHERE token={PH}""",
             (ph_json(answers),code,ph_json(tests),score,now_iso(),token))
    c.commit(); c.close()
    return {"ok":True,"score":score}

@app.get("/api/admin/session/{token}/report.pdf")
def report(token:str, req:Request):
    require_admin(req)
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER
    import io
    r=get_session(token)
    answers=r["answers"] if isinstance(r["answers"],dict) else json.loads(r["answers"] or "{}")
    tests=r["coding_tests"] if isinstance(r["coding_tests"],dict) else json.loads(r["coding_tests"] or "{}")
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=36,leftMargin=36,topMargin=36,bottomMargin=36)
    st=getSampleStyleSheet(); title=st["Title"]; title.alignment=TA_CENTER
    story=[Paragraph("Frontend Developer – React Assessment Report",title),
           Spacer(1,10),Paragraph(f"<b>Candidate:</b> {r['candidate_name']}<br/><b>Email:</b> {r['email']}<br/><b>Score:</b> {r['score']}/100",st["BodyText"]),Spacer(1,14)]
    data=[["Item","Status","Score"]]
    for i in range(1,21):
        a=str(answers.get(f"q{i}","")).strip()
        data.append([f"Q{i}", "ATTEMPTED" if a else "NOT ATTEMPTED", "—" if not a else "0–5"])
    data.append(["Live Coding","ATTEMPTED" if r["code"].strip() else "NOT ATTEMPTED","0–10"])
    tb=Table(data,colWidths=[90,150,100]); tb.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.5,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.lightgrey),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold")]))
    story += [tb,Spacer(1,14),Paragraph(f"<b>Proctoring:</b> camera granted: {bool(r.get('camera_granted'))} • policy violations: {int(r.get('violation_count') or 0)}",st["BodyText"]),Spacer(1,8),Paragraph("Automated screening score is a rubric aid; review answers and code manually before a hiring decision.",st["BodyText"])]
    doc.build(story); buf.seek(0)
    return Response(content=buf.read(),media_type="application/pdf",
                    headers={"Content-Disposition":f'inline; filename="react-assessment-{token}.pdf"'})
