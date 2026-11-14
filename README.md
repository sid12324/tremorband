# TremorBand

TremorBand is a monitoring aid, not a diagnostic device.

Milestone 1 is a local API, a simulated band, and the Live page. Milestone 2 adds the 104 Hz feature pipeline. Milestone 3 classifies each window as still, voluntary, or tremor and prints one JSON object per window on serial. `backend/app/serial_bridge.py` posts those lines through the same ingest route as HTTP. `backend/agent/` and `firmware/rig/` are still empty. There is no model or agent command. Labels are measurement classes, not a diagnosis.

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

## SELFTEST

From the repo root:

```bash
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I firmware/band/include \
  firmware/band/src/signal.cpp firmware/band/native/selftest_main.cpp \
  -o firmware/band/build-host/selftest -lm
./firmware/band/build-host/selftest
```

The line reports `acc_peak_hz` and `gyro_peak_hz` for a synthetic 5 Hz sine. On a flashed band, the same command is the serial line `selftest` at 115200 baud. The sketch then prints one JSON window per hop of 128 samples.

## Feature parity

From the repo root:

```bash
python3 -m unittest ml.tests.test_feature_parity
```

The test compiles the firmware pipeline and checks it against `ml/features.py` on 3, 5, and 8 Hz sinusoids plus noise. It also checks the still, voluntary, and tremor rule.

## Guided tests and Wi-Fi ingest

From the repo root, with the API already running:

```bash
python3 -m unittest ml.tests.test_milestone4
```

That build runs the haptic patterns, the rest, postural, finger-to-nose, tapping, and gait sequence, and posts one ingest batch. A window recorded while the motor is on has `vibrating: true` and is left out of the session summary. On a flashed band the same commands are `run_test:rest`, `cancel_test`, and `vibrate:ALERT` over serial, or `GET /api/device/{id}/commands` over Wi-Fi. Copy `firmware/band/include/secrets.h.example` to `secrets.h` before enabling Wi-Fi. `secrets.h` stays untracked.

## Serial bridge

From `backend/`, with the virtualenv activated and the API already running:

```bash
python -m app.serial_bridge --port - < windows.jsonl
```

`--port -` reads JSON lines from stdin. Pass a serial device path, such as `--port /dev/ttyACM0`, when a band is plugged in. Each `type: window` line is posted to `/api/ingest`. The Live page lists bands; choose `band-01` to see those windows.

From `backend/`:

```bash
python -m unittest tests.test_serial_bridge
```
