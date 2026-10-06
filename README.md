# StudentHub (roles: admin, teacher, student)

## Run locally
1. `python -m venv .venv` then activate it, then `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your MySQL details
3. `python init_db.py --demo` (creates tables, the admin, and sample data; drop `--demo` for a clean start)
4. `python app.py` and open http://127.0.0.1:5000

Delete the old `db_config.py` and `studenthub.sql`. Settings now come from `.env`.

## Demo logins (after `--demo`)
| Role | Email | Password |
|---|---|---|
| Admin | admin@studenthub.com | admin123 (forced change on first login) |
| Teacher | teacher@studenthub.com | teacher123 |
| Student | aarav@example.com | 14052003 (DOB as DDMMYYYY) |

Students already in your DB: log in as admin, open Students, click **Generate missing logins**.

## Deploy (Aiven MySQL + Vercel)
1. Create a free Aiven MySQL service. Download its CA certificate and save it as `ca.pem` in the project root.
2. In `.env`, set the Aiven host, port, user, password, DB name (usually `defaultdb`) and `DB_SSL=true`. Run `python init_db.py` once from your machine to create the tables and admin.
3. Push to GitHub and import into Vercel. Add the same variables (`SECRET_KEY`, `DB_*`, `DB_SSL`) in Project Settings > Environment Variables. Do not set `ADMIN_*` there.
4. If CSS 404s on Vercel, move the `static` files into a `public/static` folder.

## Notes
- Folder is `static` (lowercase). Linux hosts are case-sensitive.
- Attendance dates default to the server date (UTC on Vercel). Pick the date manually if it is off by a day.
- Not included (future work): CSRF tokens, login rate limiting.
