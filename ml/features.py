"""Python reference for the firmware feature pipeline.

TB_FS_HZ in firmware/band/include/config.h is 104.0. FS_HZ here is that same
constant. The biquad and Hann formulas follow esp-dsp 1.8.2
(dsps_biquad_gen_lpf_f32, dsps_biquad_gen_hpf_f32, dsps_biquad_f32_ansi,
dsps_wind_hann_f32). Numbers are measurements, not a diagnosis.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

FS_HZ = 104.0
WINDOW_N = 256
HOP = 128
HPF_HZ = 2.0
LPF_HZ = 15.0
STILL_ACC_RMS = 0.08
STILL_GYRO_RMS = 1.0
TREMOR_SHARPNESS = 0.55
TREMOR_HZ_MIN = 3.0
TREMOR_HZ_MAX = 12.0
PEAK_TOL_HZ = 0.15
PI = 3.141592653589793
SELFTEST_SAMPLES = 1024


@dataclass
class StreamFeatures:
    peak_hz: float
    band_power: float
    rms: float
    sharpness: float
    spectral_entropy: float
    zero_crossing_rate: float
    band_ratio: float


@dataclass
class WindowFeatures:
    acc: StreamFeatures
    gyro: StreamFeatures
    amp_deg: float
    disp_mm: float
    log_amp: float

    def as_dict(self) -> dict[str, float | str]:
        values: dict[str, float | str] = {}
        for suffix, stream in (("acc", self.acc), ("gyro", self.gyro)):
            values[f"peak_hz_{suffix}"] = stream.peak_hz
            values[f"band_power_{suffix}"] = stream.band_power
            values[f"rms_{suffix}"] = stream.rms
            values[f"sharpness_{suffix}"] = stream.sharpness
            values[f"entropy_{suffix}"] = stream.spectral_entropy
            values[f"zcr_{suffix}"] = stream.zero_crossing_rate
            values[f"ratio_{suffix}"] = stream.band_ratio
        values["amp_deg"] = self.amp_deg
        values["disp_mm"] = self.disp_mm
        values["log_amp"] = self.log_amp
        values["label"] = rule_label(self)
        return values


class _Biquad:
    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float) -> None:
        self.b0 = b0
        self.b1 = b1
        self.b2 = b2
        self.a1 = a1
        self.a2 = a2
        self.w0 = 0.0
        self.w1 = 0.0

    def process(self, sample: float) -> float:
        d0 = sample - self.a1 * self.w0 - self.a2 * self.w1
        output = self.b0 * d0 + self.b1 * self.w0 + self.b2 * self.w1
        self.w1 = self.w0
        self.w0 = d0
        return output


def _make_lpf(f_hz: float, fs: float) -> _Biquad:
    q = 1.0 / math.sqrt(2.0)
    w0 = 2.0 * PI * (f_hz / fs)
    cosine = math.cos(w0)
    sine = math.sin(w0)
    alpha = sine / (2.0 * q)
    b0 = (1.0 - cosine) / 2.0
    b1 = 1.0 - cosine
    b2 = b0
    a0 = 1.0 + alpha
    return _Biquad(b0 / a0, b1 / a0, b2 / a0, (-2.0 * cosine) / a0, (1.0 - alpha) / a0)


def _make_hpf(f_hz: float, fs: float) -> _Biquad:
    q = 1.0 / math.sqrt(2.0)
    w0 = 2.0 * PI * (f_hz / fs)
    cosine = math.cos(w0)
    sine = math.sin(w0)
    alpha = sine / (2.0 * q)
    b0 = (1.0 + cosine) / 2.0
    b1 = -(1.0 + cosine)
    b2 = b0
    a0 = 1.0 + alpha
    return _Biquad(b0 / a0, b1 / a0, b2 / a0, (-2.0 * cosine) / a0, (1.0 - alpha) / a0)


def _magnitudes(x: list[float], y: list[float], z: list[float]) -> list[float]:
    return [math.sqrt(x[i] * x[i] + y[i] * y[i] + z[i] * z[i]) for i in range(len(x))]


def _bandpass(samples: list[float], hpf_hz: float, lpf_hz: float, fs: float) -> list[float]:
    high = _make_hpf(hpf_hz, fs)
    low = _make_lpf(lpf_hz, fs)
    return [low.process(high.process(sample)) for sample in samples]


def _forward_fft(samples: list[float]) -> tuple[list[float], list[float]]:
    n = len(samples)
    real = list(samples)
    imag = [0.0] * n
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while (j & bit) != 0:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            real[i], real[j] = real[j], real[i]
            imag[i], imag[j] = imag[j], imag[i]
    length = 2
    while length <= n:
        angle = -2.0 * PI / length
        wlen_re = math.cos(angle)
        wlen_im = math.sin(angle)
        half = length // 2
        for start in range(0, n, length):
            w_re = 1.0
            w_im = 0.0
            for k in range(half):
                even = start + k
                odd = start + k + half
                v_re = real[odd] * w_re - imag[odd] * w_im
                v_im = real[odd] * w_im + imag[odd] * w_re
                u_re = real[even]
                u_im = imag[even]
                real[even] = u_re + v_re
                imag[even] = u_im + v_im
                real[odd] = u_re - v_re
                imag[odd] = u_im - v_im
                next_re = w_re * wlen_re - w_im * wlen_im
                next_im = w_re * wlen_im + w_im * wlen_re
                w_re = next_re
                w_im = next_im
        length <<= 1
    return real, imag


def _hann_at(index: int, length: int) -> float:
    scale = 1.0 / (length - 1)
    return 0.5 * (1.0 - math.cos(index * 2.0 * PI * scale))


def _features_for_window(filtered: list[float], fs: float) -> StreamFeatures:
    n = len(filtered)
    square_sum = 0.0
    crossings = 0
    for i, sample in enumerate(filtered):
        square_sum += sample * sample
        if i > 0:
            previous = filtered[i - 1]
            if (previous >= 0.0 and sample < 0.0) or (previous < 0.0 and sample >= 0.0):
                crossings += 1
    rms = math.sqrt(square_sum / n)
    zcr = crossings / (n - 1)
    windowed = [filtered[i] * _hann_at(i, n) for i in range(n)]
    real, imag = _forward_fft(windowed)
    bins = n // 2
    power = [real[k] * real[k] + imag[k] * imag[k] for k in range(bins + 1)]

    peak_k = 0
    peak_power = -1.0
    band_power = 0.0
    sharp_den = 0.0
    have_peak = False
    for k in range(bins + 1):
        freq = k * fs / n
        p = power[k]
        if 2.0 <= freq <= 12.0 and (not have_peak or p > peak_power):
            peak_power = p
            peak_k = k
            have_peak = True
        if 3.0 <= freq <= 12.0:
            band_power += p
        if 2.0 <= freq <= 15.0:
            sharp_den += p

    delta = 0.0
    if 0 < peak_k < bins:
        left = power[peak_k - 1]
        center = power[peak_k]
        right = power[peak_k + 1]
        denom = left - 2.0 * center + right
        if abs(denom) > 1e-20:
            delta = 0.5 * (left - right) / denom
    peak_hz = (peak_k + delta) * fs / n

    sharp_num = 0.0
    total = 0.0
    for k in range(bins + 1):
        freq = k * fs / n
        p = power[k]
        if abs(freq - peak_hz) <= 0.5:
            sharp_num += p
        if k >= 1:
            total += p

    entropy = 0.0
    if total > 0.0:
        for k in range(1, bins + 1):
            p = power[k]
            if p > 0.0:
                share = p / total
                entropy -= share * math.log(share)

    return StreamFeatures(
        peak_hz=peak_hz,
        band_power=band_power,
        rms=rms,
        sharpness=(sharp_num / sharp_den) if sharp_den > 0.0 else 0.0,
        spectral_entropy=entropy,
        zero_crossing_rate=zcr,
        band_ratio=(band_power / total) if total > 0.0 else 0.0,
    )


def compute_windows(
    ax: list[float],
    ay: list[float],
    az: list[float],
    gx: list[float],
    gy: list[float],
    gz: list[float],
    hpf_hz: float = HPF_HZ,
    lpf_hz: float = LPF_HZ,
) -> list[WindowFeatures]:
    """Band-pass magnitude streams and return one feature row per hop."""
    n = len(ax)
    if any(len(axis) != n for axis in (ay, az, gx, gy, gz)):
        raise ValueError("IMU axes must have the same length")
    acc = _bandpass(_magnitudes(ax, ay, az), hpf_hz, lpf_hz, FS_HZ)
    gyro = _bandpass(_magnitudes(gx, gy, gz), hpf_hz, lpf_hz, FS_HZ)
    rows: list[WindowFeatures] = []
    if len(acc) < WINDOW_N:
        return rows
    for start in range(0, len(acc) - WINDOW_N + 1, HOP):
        acc_features = _features_for_window(acc[start : start + WINDOW_N], FS_HZ)
        gyro_features = _features_for_window(gyro[start : start + WINDOW_N], FS_HZ)
        gyro_peak = math.sqrt(2.0) * gyro_features.rms
        acc_peak = math.sqrt(2.0) * acc_features.rms
        amp_deg = gyro_peak / (2.0 * PI * gyro_features.peak_hz) if gyro_features.peak_hz > 1e-6 else 0.0
        if acc_features.peak_hz > 1e-6:
            omega = 2.0 * PI * acc_features.peak_hz
            disp_mm = (acc_peak / (omega * omega)) * 1000.0
        else:
            disp_mm = 0.0
        rows.append(
            WindowFeatures(
                acc=acc_features,
                gyro=gyro_features,
                amp_deg=amp_deg,
                disp_mm=disp_mm,
                log_amp=math.log10(max(amp_deg, 1e-12)),
            )
        )
    return rows


def rule_label(row: WindowFeatures) -> str:
    """Still, voluntary, or tremor for one window. This is not a diagnosis."""
    if row.acc.rms < STILL_ACC_RMS and row.gyro.rms < STILL_GYRO_RMS:
        return "still"
    low = TREMOR_HZ_MIN - PEAK_TOL_HZ
    high = TREMOR_HZ_MAX + PEAK_TOL_HZ

    def is_tremor(stream: StreamFeatures) -> bool:
        return stream.sharpness >= TREMOR_SHARPNESS and low <= stream.peak_hz <= high

    if is_tremor(row.acc) or is_tremor(row.gyro):
        return "tremor"
    return "voluntary"


def selftest_samples() -> tuple[list[float], list[float], list[float], list[float], list[float], list[float]]:
    """Biased 5 Hz sine used by the firmware SELFTEST command."""
    ax = [0.0] * SELFTEST_SAMPLES
    ay = [0.0] * SELFTEST_SAMPLES
    az = [0.0] * SELFTEST_SAMPLES
    gx = [0.0] * SELFTEST_SAMPLES
    gy = [0.0] * SELFTEST_SAMPLES
    gz = [0.0] * SELFTEST_SAMPLES
    for i in range(SELFTEST_SAMPLES):
        sine = math.sin(2.0 * PI * 5.0 * (i / FS_HZ))
        az[i] = 9.81 + 0.8 * sine
        gx[i] = 30.0 + 20.0 * sine
    return ax, ay, az, gx, gy, gz


def synthetic_imu(
    freq_hz: float,
    noise_a: float,
    noise_g: float,
    n: int,
    seed: int,
) -> tuple[list[float], list[float], list[float], list[float], list[float], list[float]]:
    """A sine on accel and gyro magnitudes, plus Gaussian noise."""
    rng = random.Random(seed)
    ax: list[float] = []
    ay: list[float] = []
    az: list[float] = []
    gx: list[float] = []
    gy: list[float] = []
    gz: list[float] = []
    for i in range(n):
        sine = math.sin(2.0 * PI * freq_hz * (i / FS_HZ))
        ax.append(rng.gauss(0.0, noise_a))
        ay.append(rng.gauss(0.0, noise_a))
        az.append(9.81 + 0.8 * sine + rng.gauss(0.0, noise_a))
        gx.append(30.0 + 20.0 * sine + rng.gauss(0.0, noise_g))
        gy.append(rng.gauss(0.0, noise_g))
        gz.append(rng.gauss(0.0, noise_g))
    return ax, ay, az, gx, gy, gz
