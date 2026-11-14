# TremorBand

TremorBand is a monitoring aid, not a diagnostic device.

Milestone 1 is a local API, a simulated band, and the Live page. `firmware/`, `ml/`, and `backend/agent/` are empty placeholders for later milestones. This milestone has no firmware, model, or agent commands.

The simulator posts window features about every 1.2 seconds (104 Hz sampling, 256-sample windows, hop 128). It cycles through still, voluntary movement, and tremor, with a little noise and a slow amplitude envelope.

## API

From `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs

`--reload-dir app` keeps the reloader off the SQLite file. The database is created at `backend/data/tremorband.db`.

## Simulated band

From `backend/`, with the virtualenv activated:

```bash
python scripts/sim_device.py
```

Optional flags: `--base-url`, `--device-id`, `--peak-hz`, `--amp-deg`, `--hour-seconds`, `--seed`.

## Live page

From `dashboard/`:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173 . The page shows band connection, peak Hz, amplitude, and the current window label.

Stop each process with Ctrl+C.
