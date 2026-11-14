# TremorBand

TremorBand is a monitoring aid, not a diagnostic device.

Milestone 1 is a local API, a simulated band, and the Live page. Milestone 2 adds the 104 Hz feature pipeline. Milestone 3 classifies each window as still, voluntary, or tremor and prints one JSON object per window on serial. `backend/app/serial_bridge.py` posts those lines through the same ingest route as HTTP. Milestone 5 adds the SG90 calibration sketch and the Calibration page. Milestone 6 trains a small window model on synthetic sessions and exports it to the band. Milestone 7 adds personal baselines, a synthetic seven-day log, and the Trends and Log pages. `backend/agent/` is still empty. There is no agent command. Labels are measurement classes, not a diagnosis. The pages do not suggest a dose.

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

`--port -` reads JSON lines from stdin. Pass a serial device path, such as `--port /dev/ttyACM0`, when a band is plugged in. Each `type: window` line is posted to `/api/ingest`. A `type: rig` line is posted to `/api/rig/run`. The Live page lists bands; choose `band-01` to see those windows.

From `backend/`:

```bash
python -m unittest tests.test_serial_bridge
```

## Calibration rig

From the repo root:

```bash
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I firmware/rig \
  firmware/rig/rig_control.cpp firmware/rig/native/rig_main.cpp \
  -o firmware/rig/build-host/rig_test -lm
./firmware/rig/build-host/rig_test
```

`rig_test` checks the sine step, the 600 deg/s amplitude cut, a late loop's measured frequency, and the 3 to 8 Hz sweep. On the servo board, `firmware/rig/rig.ino` uses the same controller. Servo signal is pin 9, with a separate 5 V supply and a common ground. Serial commands at 115200 are `f <hz>`, `a <deg>`, `stop`, and `sweep`.

From `backend/`, with the virtualenv activated:

```bash
python -m unittest tests.test_rig
```

That run compiles the controller test and checks `POST /api/rig/run` plus `GET /api/rig/accuracy`. Open http://127.0.0.1:5173/#/calibration for the setpoint form, live error, per-frequency table, scatter plot, and MAE.

## Window model

From the repo root, with the packages in `ml/requirements.txt` installed:

```bash
python3 -m ml.collect --synthetic --out-dir ml/data
python3 -m ml.train --data-dir ml/data --model-dir ml/model --plot-dir ml/plots
python3 -m ml.export_model
python3 -m unittest ml.tests.test_milestone6
```

`ml/collect.py --synthetic` writes labeled CSVs with `synthetic=yes`. A rig session is one of the three tremor sessions for each person, so rig windows stay under half of the tremor class. `ml/train.py` reports leave-one-person-out precision, recall, and a confusion plot for a depth-limited random forest and a decision tree. The forest is the exported model. `ml/export_model.py` writes `firmware/band/src/model_params.h` and the pickle at `ml/model/tremor_model.pkl` is what `ml.inference.p_tremor_server` scores. On the band, the rule gate still decides still and voluntary; the model only rescores a tremor candidate.

A live capture, when a band is connected, is:

```bash
python3 -m ml.collect --port /dev/ttyACM0 --out ml/data/session.csv --person-id p01 --label tremor --wrist left --pose rest --source human --hz 5 --seconds 20
```

That command was not run here. It sends `set_mode:forward`, counts down, and ticks a 5 Hz metronome while it records.

## Trends and the symptom log

From `backend/`, with the virtualenv activated:

```bash
python -m unittest tests.test_analytics
python scripts/seed_demo.py
```

The unit test checks the personal baseline, z-scores, the comparison-line steps, wearing-off bins, symptom-tag association, and window exclusions. `scripts/seed_demo.py` writes seven days for the band `demo-band`. Every session has `is_synthetic` set. Running it again replaces that band, doses marked `synthetic demo`, and notes marked `Synthetic demo`. Other bands stay.

Open http://127.0.0.1:5173/#/trends for log amplitude, the baseline band, logged-dose markers, hours after a logged dose, tremor hours, and the comparison-line buttons. Open http://127.0.0.1:5173/#/log to save a dose or a symptom rating. Both pages show the monitoring-aid line.
