# Portfolio — Civitas production loop

Landing statiche prodotte dal **production loop** (`production/`):

- Output: `vault/08-PORTFOLIO/{slug}/index.html` + `styles.css`
- Score: rubric rule-based Awwwards-ish (0–100)
- Critique: `vault/04-LEARNINGS/YYYY-MM-DD-production-{slug}.md`

Trigger OPS (Living :9300):

```bash
curl -s -X POST http://127.0.0.1:9300/v1/production/run \
  -H 'Content-Type: application/json' \
  -d '{"slug":"demo-landing","crew_size":3}'
```

Script locale (senza server):

```bash
python scripts/run_production_loop.py --agents 6 --tick 42
```
