# FoodSight

An AI-first Food & Beverage location intelligence platform that transforms Food & Beverage data into a knowledge graph, enabling conversational analytics and interactive map visualizations to help analysts find market opportunities and customers discover restaurants.

## Running the App (Backend + Frontend)

The backend (FastAPI) and frontend (React) run in Docker. PostgreSQL does not: it runs on your own machine and the backend connects to it.

**Requirements**

- Docker Desktop, running
- PostgreSQL on `localhost:5432` with the FoodSight database (its name is `DB_NAME` in `.env`; PostGIS is not needed)
- A `.env` file in the project root (copy `.env.example` and fill in the values)

**Commands**

```powershell
docker compose up -d            # start
docker compose down             # stop
docker compose up -d --build -V # rebuild, only after changing dependencies
docker compose logs -f backend  # view backend logs
```

**Pages**

| Page | URL |
|---|---|
| Login | http://localhost:5173/login |
| Register | http://localhost:5173/register |
| Forgot password | http://localhost:5173/forgot-password |
| Chat (placeholder, login required) | http://localhost:5173/chat |

**Accounts and login**

- Register with a username, email and password, then open the verification link sent by email. Login is blocked until the email is verified.
- Passwords need at least 8 characters with an uppercase letter, a lowercase letter, a number and a special character.
- A login session lasts 1 hour. Verification and reset links last 15 minutes.
- On the dashboard, Settings → Edit Profile (or your name at the bottom of the sidebar) shows your email and name, lets you change the name, and lets you upload a profile picture (JPG, PNG or WebP, up to 2 MB) by clicking the picture. Settings → Change Password needs your current password and logs out your other browsers. Picture upload needs `db/migrations/025_user_picture.sql` to have been run.
- Without `SMTP_USER` and `SMTP_PASSWORD` in `.env`, no email is sent. The link is printed in the backend log instead: run `docker compose logs backend` and copy it.
- Without `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`, "Continue with Google" shows a "not set up" message. See `.env.example` for how to get both.

**Database changes**

Table structures are documented in `db/schema/tables.md`. To change a table, add a numbered SQL file in `db/migrations/`, run it in pgAdmin, then run `python db/dump_schema.py` to refresh the document.

**URLs**

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000/api/v1 |
| API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/api/v1/health |

Code changes in `backend/` and `frontend/` reload automatically, so no rebuild is needed while developing.

## Data pipeline

The data comes from OpenStreetMap (every food business in Petaling Jaya, and what is around it) and Google Places (hours, price, facilities, rating, reviews). An AI model (Gemma, through the Gemini API) settles where the two sources disagree and profiles each restaurant. The result goes into PostgreSQL and then into a Neo4j knowledge graph.

**Requirements:** Python 3.11 (`python -m pip install -r requirements.txt`), PostgreSQL running, Neo4j Desktop with the `FoodSight` instance started (for stage 8), and in `.env`: `GOOGLE_PLACES_API_KEY`, `GEMINI_API_KEY`, the `DB_*` and `NEO4J_*` values.

**The 8 stages**, run in this order from the project folder:

| Stage | Command | What it does |
|---|---|---|
| 1 | `python run_1_extraction.py` | OSM and Google data into `data/1_raw/`; then the change check and the next extraction date; then Google's first 3 photos of each restaurant that still needs them (`data/cache/photos/`) |
| 2 | `python run_2_preprocessing.py` | cleans each source |
| 3 | `python run_3_merging.py` | joins OSM and Google by rules (no AI) |
| 4 | `python run_4_profiling.py` | the AI: chooses between the sources and profiles each new or changed restaurant; review sentiments |
| 5 | `python run_5_validation.py` | checks every record before it is loaded |
| 6 | `python run_6_clustering.py` | finds food clusters (DBSCAN) |
| 7 | `python run_7_loading.py` | brings PostgreSQL up to date, photos included (`--dry-run` shows the changes and undoes them; photos need `db/migrations/026_restaurant_photo.sql` to have been run) |
| 8 | `python run_8_graph.py` | copies what changed into Neo4j (`--fresh` rebuilds the whole graph) |

**The daily update:** `python run_update.py` does all of this by itself: it extracts what is due (OpenStreetMap and Google each have their own schedule, which an AI adjusts from how much changed), runs the stages, and continues the next day if something stopped halfway. Windows Task Scheduler runs it every night at midnight. `python run_update.py --status` shows what is due; `--force osm|google|both` extracts now. A new decision in `src/reference/` (from the admin review page or by hand) is applied that night too.

**The admin review page:** `http://localhost:5173/admin`, or **Review** in the chat sidebar, for admins only. It shows what the pipeline needs a person for (Google matches to check, restaurants gone from OpenStreetMap, nearby places counted wrongly) and writes your decisions into the files in `src/reference/` for the next nightly update. To make an account an admin, run this in pgAdmin: `UPDATE auth.users SET is_superuser = true WHERE email = 'you@example.com';`

**Where things are:**

| Folder | What |
|---|---|
| `data/logs/` | everything each run printed, one file per day |
| `data/review/` | things that need you: Google matches to check, restaurants gone from OpenStreetMap, failed AI answers (the admin review page shows them) |
| `data/reports/` | what changed in each extraction |
| `data/archive/` | a dated copy of each extraction that changed something |
| `data/state/` | the schedule, the graph's to-do list, the daily runner's bookmark |
| `src/reference/` | files you edit by hand or through the admin review page: categories (by hand only), Google match decisions, nearby exclusions, decisions about removed restaurants |

The full description of every rule is in [CLAUDE.md](CLAUDE.md).
