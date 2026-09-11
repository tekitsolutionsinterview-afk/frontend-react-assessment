# Frontend Developer – React Assessment Platform

A new, independent assessment platform for 1–2 year Frontend Developer (React) candidates.

## Assessment
- 45 minutes
- 100 points
- 20 difficult technical questions
- Mandatory questions
- Live JavaScript coding challenge
- Autosave
- Automatic submission on timeout
- Admin authentication
- Candidate credential generation
- PostgreSQL on Render / SQLite locally
- Individual PDF reports

## Render environment variables
Set:
- DATABASE_URL = your Render PostgreSQL internal/external connection string as appropriate
- ADMIN_PASSWORD = a strong password you choose
- ADMIN_SECRET = a long random secret

Never commit secrets to GitHub.

## Start
Build: `pip install -r requirements.txt`
Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Admin: `/admin`
Candidate: `/`
Health: `/health`

## Repository structure
Keep `main.py` inside `app/` and both HTML files inside `app/static/`. Do not upload replacement copies to the repository root.
