"""Read JSON lines from a band and ingest them through the API.

TremorBand is a monitoring aid, not a diagnostic device. A window label is a
measurement class, not a diagnosis.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import httpx
from pydantic import ValidationError
from sqlmodel import Session

from app.routes.devices import heartbeat
from app.routes.ingest import ingest
from app.schemas import HeartbeatIn, IngestBody, SessionIn, WindowIn, utcnow

logger = logging.getLogger(__name__)


class SerialParseError(ValueError):
    """A JSON line was readable but not a window or heartbeat this bridge stores."""


def parse_serial_line(line: str, *, now: datetime | None = None) -> IngestBody | tuple[str, HeartbeatIn] | None:
    """Turn one serial line into an ingest body or a heartbeat.

    Blank lines, logs, and raw sample lines are ignored. A window without an
    ISO timestamp is stamped with `now`.
    """
    text = line.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SerialParseError("line is not JSON") from exc
    if not isinstance(payload, dict):
        raise SerialParseError("line is not an object")
    kind = payload.get("type")
    if kind in {"log", "raw"}:
        return None
    device_id = payload.get("device_id") or "band-01"
    if not isinstance(device_id, str):
        raise SerialParseError("device_id is not a string")
    if kind == "heartbeat":
        body = HeartbeatIn(
            name=payload.get("name") if isinstance(payload.get("name"), str) else None,
            battery=_optional_float(payload.get("battery")),
            rssi=_optional_float(payload.get("rssi")),
            fw_version=payload.get("fw_version") if isinstance(payload.get("fw_version"), str) else None,
            mode=payload.get("mode") if isinstance(payload.get("mode"), str) else "serial",
            uptime_s=_optional_float(payload.get("uptime_s")),
        )
        return device_id, body
    if kind == "session":
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        started = _timestamp(payload.get("ts_start"), now or utcnow())
        ended = _timestamp(payload.get("ts_end"), started)
        quality = _optional_float(payload.get("quality"))
        test_type = payload.get("test_type") if isinstance(payload.get("test_type"), str) else "rest"
        return IngestBody(
            device_id=device_id,
            device_name=device_id,
            sessions=[
                SessionIn(
                    ts_start=started,
                    ts_end=ended,
                    test_type=test_type,
                    summary=summary,
                    quality=quality,
                    is_synthetic=bool(payload.get("is_synthetic", False)),
                )
            ],
        )
    if kind != "window":
        return None
    stamp = _timestamp(payload.get("ts"), now or utcnow())
    test_type = payload.get("test_type") if isinstance(payload.get("test_type"), str) else None
    window = WindowIn(
        ts=stamp,
        test_type=test_type,
        peak_hz=float(payload["peak_hz"]),
        band_power=float(payload["band_power"]),
        rms=float(payload["rms"]),
        sharpness=float(payload["sharpness"]),
        amp_deg=float(payload["amp_deg"]),
        disp_mm=float(payload["disp_mm"]),
        log_amp=float(payload["log_amp"]),
        label=payload["label"],
        p_tremor=float(payload["p_tremor"]),
        vibrating=bool(payload.get("vibrating", False)),
    )
    name = payload.get("device_name")
    return IngestBody(
        device_id=device_id,
        device_name=name if isinstance(name, str) else device_id,
        windows=[window],
    )


def apply_serial_line(session: Session, line: str, *, now: datetime | None = None) -> str | None:
    """Store one line with the same ingest and heartbeat functions the HTTP routes use."""
    parsed = parse_serial_line(line, now=now)
    if parsed is None:
        return None
    if isinstance(parsed, tuple):
        device_id, body = parsed
        heartbeat(device_id, body, session)
        return "heartbeat"
    ingest(parsed, session)
    if parsed.sessions and not parsed.windows:
        return "session"
    return "window"


def consume_line(session: Session, line: str, *, now: datetime | None = None) -> str:
    """Apply one line. A bad line is reported and does not stop the reader."""
    try:
        return apply_serial_line(session, line, now=now) or "ignored"
    except (SerialParseError, ValidationError, KeyError, TypeError, ValueError):
        logger.warning("skipped serial line")
        return "rejected"


def post_line(base_url: str, line: str, client: httpx.Client) -> str:
    """Post one line to a running API, which stores it through the HTTP ingest route."""
    parsed = parse_serial_line(line)
    if parsed is None:
        return "ignored"
    root = base_url.rstrip("/")
    if isinstance(parsed, tuple):
        device_id, body = parsed
        response = client.post(f"{root}/api/device/{device_id}/heartbeat", json=body.model_dump(mode="json"))
        response.raise_for_status()
        return "heartbeat"
    response = client.post(f"{root}/api/ingest", json=parsed.model_dump(mode="json"))
    response.raise_for_status()
    if parsed.sessions and not parsed.windows:
        return "session"
    return "window"


def forward_pending_commands(base_url: str, device_id: str, client: httpx.Client, output: Any | None) -> None:
    """Write queued command lines to the band when the bridge owns the serial port."""
    if output is None:
        return
    root = base_url.rstrip("/")
    response = client.get(f"{root}/api/device/{device_id}/commands")
    if response.status_code == 404:
        return
    response.raise_for_status()
    for item in response.json():
        command = item.get("cmd")
        if isinstance(command, str) and command:
            data = (command + "\n").encode()
            try:
                output.write(data)
            except TypeError:
                output.write(command + "\n")
            if hasattr(output, "flush"):
                output.flush()


def iter_source_lines(port: str, baud: int) -> Iterator[str]:
    """Yield text lines from stdin, a file, or a serial port."""
    if port == "-":
        yield from sys.stdin
        return
    path = Path(port)
    if path.is_file():
        with path.open(encoding="utf-8") as handle:
            yield from handle
        return
    import serial

    with serial.Serial(port, baud, timeout=1) as handle:
        while True:
            raw = handle.readline()
            if raw:
                yield raw.decode(errors="replace")


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return fallback


def main(argv: list[str] | None = None) -> int:
    """Read serial JSON lines and post each window to the API."""
    parser = argparse.ArgumentParser(description="Ingest TremorBand serial JSON lines")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--port", default="-", help="Serial port, a text file, or - for stdin")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    last_device = "band-01"
    serial_output = None
    if args.port != "-" and not Path(args.port).is_file():
        import serial

        serial_output = serial.Serial(args.port, args.baud, timeout=1)
    try:
        with httpx.Client(timeout=5.0) as client:
            source = iter_source_lines(args.port, args.baud) if serial_output is None else _serial_lines(serial_output)
            for line in source:
                try:
                    kind = post_line(args.base_url, line, client)
                except (SerialParseError, ValidationError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
                    logger.warning("skipped serial line: %s", exc.__class__.__name__)
                    continue
                if kind == "ignored":
                    continue
                parsed = parse_serial_line(line)
                if isinstance(parsed, IngestBody):
                    last_device = parsed.device_id
                elif isinstance(parsed, tuple):
                    last_device = parsed[0]
                logger.info("serial %s device=%s", kind, last_device)
                try:
                    forward_pending_commands(args.base_url, last_device, client, serial_output)
                except httpx.HTTPError as exc:
                    logger.warning("command poll failed: %s", exc.__class__.__name__)
    finally:
        if serial_output is not None:
            serial_output.close()
    return 0


def _serial_lines(handle: Any) -> Iterator[str]:
    while True:
        raw = handle.readline()
        if raw:
            yield raw.decode(errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
