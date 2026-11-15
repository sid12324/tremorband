# TremorBand

TremorBand is a monitoring aid, not a diagnostic device.

The site has two pages. Session turns capture on and off. Each time capture turns on, a new session starts, and windows ingested while it is on belong to that session. Turning it off ends the session. Analysis asks the deep agent in `backend/agent/` to review stored sessions and describe the movement. The analysis cites stored numbers, labels synthetic sessions as simulated, and does not diagnose or suggest medication.

Milestone 1 is a local API and a simulated band. Milestone 2 adds the 104 Hz feature pipeline. Milestone 3 classifies each window as still, voluntary, or tremor and prints one JSON object per window on serial. `backend/app/serial_bridge.py` posts those lines through the same ingest route as HTTP. Milestone 6 trains a small window model on synthetic sessions and exports it to the band. Labels are measurement classes, not a diagnosis.

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

## Session and Analysis

From `dashboard/`:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173 . Session is the on/off control. Analysis reviews the stored sessions.

The API reads two environment variables and nothing else for the model:

- `OPENAI_API_KEY`
- `TREMORBAND_MODEL`

If `OPENAI_API_KEY` is set and `TREMORBAND_MODEL` is unset, the model is `openai:gpt-4o-mini`. If `OPENAI_API_KEY` is unset, the API keeps the scripted model and does not call a hosted model. Set `TREMORBAND_MODEL` to a `provider:model` string when you want a different hosted model. Put the key in the environment, not in the repo, and do not log it.

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

The unit test checks the personal baseline, z-scores, the comparison-line steps, wearing-off bins, symptom-tag association, and window exclusions. `scripts/seed_demo.py` writes seven days for the band `demo-band`. Every session has `is_synthetic` set, so Analysis labels those sessions simulated. Running it again replaces that band, doses marked `synthetic demo`, and notes marked `Synthetic demo`. Other bands stay.

## Analysis

From `backend/`, with the virtualenv activated and the API already running:

```bash
python -m unittest tests.test_agent
python -m unittest tests.test_capture
```

Open http://127.0.0.1:5173/#/analysis and choose Analyze movement. The agent cites stored peak, amplitude, and window counts. Synthetic sessions are labeled simulated. The monitoring-aid line stays on the page.

## Tests, settings, and the clinician view

Open http://127.0.0.1:5173/#/tests for rest, postural, finger-to-nose, tapping, and gait. A running test shows a countdown. Result cards read peak Hz, log amplitude, tremor percent, taps per second, decrement, and gait asymmetry when the session summary has those fields.

Open http://127.0.0.1:5173/#/settings for transport, MS mode, sleep hours, haptic intensity, demo mode, CSV export, and delete-my-data. Deleting stored rows requires the phrase `delete my data`.

Open http://127.0.0.1:5173/#/clinician for a read-only view of notes that were sent and the recorded timing sentence.

From `backend/`:

```bash
python -m unittest tests.test_movement
```

## Wiring

| Function | GPIO | Notes |
| --- | --- | --- |
| LSM6DS3 SDA | GPIO21 | 400 kHz I2C. Adafruit LSM6DS `LSM6DS3`, 104 Hz, accel ±4 g, gyro ±500 dps |
| LSM6DS3 SCL | GPIO22 | 400 kHz I2C, with SDA |
| LSM6DS3 INT1 | GPIO4 | Optional data-ready interrupt |
| Button | GPIO2 | INPUT_PULLUP. Long press is longer than 1.5 s |
| Battery sense | GPIO34 | Two 220 kOhm resistors. The divider pin is `TB_BATTERY_PIN` in `config.h` |
| Firmware LED | GPIO13 | Active low. The CH343 UART bridge is UART0: GPIO43 TX, GPIO44 RX |
| Rig servo | Pin 9 on the servo board | Separate 5 V supply and a common ground |

The band board is an ESP32-S3-DevKitC-1. The USB chip is a CH343, so flashing and the serial log use UART (esptool), not native USB-CDC. The wrist IMU is an LSM6DS3 on GPIO21 (SDA) and GPIO22 (SCL). `TB_IMU_DRIVER=TB_IMU_MPU6050` selects the MPU6050 fallback. This band has no vibration motor. The same names live in `firmware/band/include/config.h`.

## Setup

1. From `backend/`, create the virtualenv, install the package, and start the API:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

2. From `dashboard/`, install and start the page:

```bash
npm install
npm run dev
```

3. From `backend/`, with the virtualenv activated, export `OPENAI_API_KEY` only if you want the hosted model. Leave `TREMORBAND_MODEL` unset to use `openai:gpt-4o-mini` when that key is present. With no key, the scripted model stays in use. Then start the simulated band and, when you want stored sessions to review, the synthetic week:

```bash
python scripts/sim_device.py
python scripts/seed_demo.py
```

4. Copy `firmware/band/include/secrets.h.example` to `secrets.h` before a Wi-Fi build. Leave `secrets.h` and `.env` untracked.

Host checks that were run here:

```bash
python -m unittest tests.test_serial_bridge
python -m unittest tests.test_rig
python -m unittest tests.test_analytics
python -m unittest tests.test_agent
python -m unittest tests.test_movement
python3 -m unittest ml.tests.test_feature_parity
python3 -m unittest ml.tests.test_milestone4
python3 -m unittest ml.tests.test_milestone6
```

Run each `tests.*` module in its own process. They each point `DATABASE_URL` at a temporary database at import time.

## Troubleshooting

**Edge Impulse on ESP32 Arduino core 3.x.** An Edge Impulse export can fail to compile because the ESP-NN kernels and that core disagree. Define `EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN 0` before the inferencing header, or pin the board core the Edge Impulse library was exported for. The on-device model in this repo is the emlearn header, so a normal build does not include that library.

**Wi-Fi.** The band reads the network name and password from `firmware/band/include/secrets.h`. If the HTTP posts never arrive, check that the laptop API is on the same network and that `TB_API_URL` in the sketch matches `http://<laptop>:8000`.

**Serial permissions.** If `serial_bridge` cannot open the port, add your user to the `dialout` group and replug the board, or run the bridge against a file with `--port -`. The bridge and the API must not both open the same device node.

**Reloader stuck on shutdown.** `--reload` waits for open connections. The simulator keeps a connection, so a save under `backend/app/` can sit on "Waiting for connections to close." Stop that uvicorn process and start the same command again. The simulator reconnects.

## Two-minute demo

TremorBand is a monitoring aid, not a diagnostic device. Say that at the start and at the end. Do not suggest a dose.

- 0:00 Open http://127.0.0.1:5173/#/session . Read the monitoring-aid line. Turn capture on. A new session starts.
- 0:30 Let the simulator or the band post windows. Those windows belong to the open session. Turn capture off. The session ends.
- 1:00 Turn capture on again. That is a different session. Turn it off when the second recording is done.
- 1:20 Open http://127.0.0.1:5173/#/analysis . Point at Simulated on the seeded sessions. Press Analyze movement.
- 1:40 Read the cited peak, amplitude, and window counts. The text does not diagnose and does not suggest medication.
- 2:00 Repeat the monitoring-aid line.
