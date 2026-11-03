# Deploying on Vercel (two projects, nothing else needed)

The demo database is a 19 MB DuckDB file committed at `demo/serve.duckdb`. The API runs as a Python function on Vercel and the dashboard is a normal Next.js project.

## 1. API project
1. In Vercel, **Add New Project**, import this repository, keep the **Root Directory** as the repository root.
2. Framework preset: **Other**. No build command. Deploy.
3. Open `https://<api-project>.vercel.app/api/health`. It should return `{"status":"ok",...}`.

How it works: `api/index.py` copies the database to `/tmp` on a cold start (Vercel's disk is otherwise read-only) and serves the FastAPI app. `vercel.json` sends every path to it and bundles `src/`, `benchmarks/` and `demo/`.

## 2. Dashboard project
1. **Add New Project**, import the same repository, set **Root Directory** to `dashboard`.
2. Add the environment variable `TALLY_API` = `https://<api-project>.vercel.app` (no trailing slash).
3. Deploy. The dashboard proxies `/api/*` to the API, so the browser only talks to one site.

## What to expect
- Decisions made in the demo (explain, resolve) are stored in the function's `/tmp` copy. They persist for a while, then reset when Vercel recycles the instance. Different visitors may land on different instances. For a portfolio demo that is fine; say so on the page.
- First request after idle takes a couple of seconds (cold start).
- To refresh the demo data: `make demo-ui`, then `cp data/ui/serve.duckdb demo/serve.duckdb`, commit, push.
- Not for real data: there is no sign-in (see SECURITY.md).
