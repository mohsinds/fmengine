# fmtrader-web

Phase 11 MVP control / observability UI for fmengine. Talks to the FastAPI review contract only.

## Start

1. API (from repo root):

```bash
uv run fmtrader api serve
```

2. UI:

```bash
cd web && npm install && npm run dev
```

Or from the repo root: `make api` in one terminal, `make ui` in another.

Default API base: `http://127.0.0.1:8000` (`NEXT_PUBLIC_API_URL`).

Open [http://localhost:3000](http://localhost:3000).
