# Deploying (free tiers)

| Part | Where | Settings |
|---|---|---|
| API | Render web service (Python, free) | Build `pip install -e ".[api]"` · Start `cp demo/serve.duckdb /tmp/trueup.duckdb && python -m trueup serve --db /tmp/trueup.duckdb --host 0.0.0.0 --port $PORT` |
| Dashboard | Vercel (Next.js) | Root Directory `dashboard` · env `TRUEUP_API=https://<api>.onrender.com` (no trailing slash) |

The API serves the bundled demo database (`demo/serve.duckdb`); decisions made in the demo live in the instance's copy and reset on restart. The dashboard proxies `/api/*` to the API, so the browser only talks to one site. The free API sleeps when idle, so the first request after a break takes up to a minute.

To refresh the demo data: `make demo-ui`, then `cp data/ui/serve.duckdb demo/serve.duckdb`, commit, push. Render redeploys on push.
