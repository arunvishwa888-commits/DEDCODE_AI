# DEDCODE AI deployment notes

This repository is a Flask application. It currently uses SQLite for local data persistence and is not yet fully migrated to Supabase PostgreSQL.

## Current state

- Local dev database: SQLite via `backend/database.py`
- Static assets: local file system under `backend/static` and `static`
- Web app entrypoint: `backend/app.py`
- Vercel entrypoint: `api/index.py`

## Vercel setup

1. Push this repo to GitHub.
2. Import the repository in Vercel.
3. Set the project framework to Python.
4. Add environment variables from `.env` (or create a production version).
5. Deploy.

Required environment variables include:

- `SECRET_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DATABASE_URL`

## Supabase setup

1. Create a new Supabase project.
2. Create a PostgreSQL database.
3. Get the connection string and keys from the project dashboard.
4. Replace SQLite calls with PostgreSQL queries before production deployment.
5. Move uploads to Supabase Storage instead of the local filesystem.

## Production warning

This app must be migrated from SQLite to PostgreSQL before it can be reliably hosted on Vercel. The generated Vercel config is a deployment-ready wrapper, but the application data layer still needs a production DB migration.

## Recommended next step

After the Supabase migration, deploy to Vercel with the environment variables above and update the local file-based storage to Supabase Storage.
