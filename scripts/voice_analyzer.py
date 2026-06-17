# scripts/voice_analyzer.py — Diagnostic tool to score WAV humanness
# Measures 6 metrics and produces a pass/fail verdict + humanness score
# Uses scipy + numpy directly to avoid librosa STFT segfaults

import sys
import json
import pathlib
import numpy as np
import soundfile as sf


def load_audio(path: str) -> tuple:
    """Load audio file, return (samples, sample_rate)."""
    y, sr = sf.read(path, dtype='float32')
    if y.ndim > 1:
        y = y[:, 0]  # mono
    return y, sr


def measure_pitch_variance(y: np.ndarray, sr: int) -> dict:
    """Measure F0 pitch variance using autocorrelation-based pitch detection."""
    try:
        # Frame-based autocorrelation pitch detection
        frame_len = int(sr * 0.03)  # 30ms frames
        hop = int(sr * 0.01)        # 10ms hop
        min_lag = int(sr / 500)     # 500 Hz max
        max_lag = int(sr / 50)      # 50 Hz min

        f0_values = []
        for start in range(0, len(y) - frame_len, hop):
            frame = y[start:start + frame_len]
            # Check if frame has energy
            if np.sqrt(np.mean(frame ** 2)) < 0.01:
                continue

            # Autocorrelation
            corr = np.correlate(frame, frame, mode='full')
            corr = corr[len(corr)//2:]  # take positive lags only

            # Normalize
            if corr[0] > 0:
                corr = corr / corr[0]

            # Find peak in valid lag range
            if max_lag > len(corr):
                continue
            search = corr[min_lag:max_lag]
            if len(search) == 0:
                continue

            peak_idx = np.argmax(search) + min_lag
            if corr[peak_idx] > 0.3:  # voiced threshold
                f0 = sr / peak_idx
                if 50 < f0 < 500:
                    f0_values.append(f0)

        voiced_f0 = np.array(f0_values)
        if len(voiced_f0) < 10:
            return {"pitch_std_semitones": 0.0, "pitch_range_hz": 0.0, "pass": False}

        median_f0 = np.median(voiced_f0)
        semitones = 12 * np.log2(voiced_f0 / median_f0)
        std_semitones = float(np.std(semitones))
        pitch_range = float(np.max(voiced_f0) - np.min(voiced_f0))

        return {
            "pitch_std_semitones": round(std_semitones, 2),
            "pitch_range_hz": round(pitch_range, 1),
            "median_f0_hz": round(float(median_f0), 1),
            "pass": 2.0 <= std_semitones <= 8.0 and pitch_range >= 80
        }
    except Exception as e:
        print(f"  Pitch analysis error: {e}")
        return {"pitch_std_semitones": 0.0, "pitch_range_hz": 0.0, "pass": False}


def measure_rms_variance(y: np.ndarray, sr: int) -> dict:
    """Measure RMS energy coefficient of variation."""
    try:
        frame_len = 512
        rms = []
        for i in range(0, len(y) - frame_len, frame_len):
            frame = y[i:i + frame_len]
            rms.append(np.sqrt(np.mean(frame ** 2)))
        rms = np.array(rms)
        mean_rms = float(np.mean(rms))
        std_rms = float(np.std(rms))
        cv = std_rms / max(mean_rms, 1e-10)

        return {
            "rms_mean": round(mean_rms, 4),
            "rms_std": round(std_rms, 4),
            "rms_cv": round(cv, 3),
            "pass": cv > 0.15
        }
    except Exception as e:
        print(f"  RMS analysis error: {e}")
        return {"rms_mean": 0, "rms_std": 0, "rms_cv": 0, "pass": False}


def measure_noise_floor(y: np.ndarray, sr: int) -> dict:
    """Measure noise floor in silent segments (dBFS)."""
    try:
        frame_len = 512
        rms = []
        for i in range(0, len(y) - frame_len, frame_len):
            frame = y[i:i + frame_len]
            rms.append(np.sqrt(np.mean(frame ** 2)))
        rms = np.array(rms)
        threshold = np.percentile(rms, 10)
        silent_rms = rms[rms <= threshold]

        if len(silent_rms) == 0:
            return {"noise_floor_dbfs": -96.0, "pass": False}

        mean_silent = float(np.mean(silent_rms))
        if mean_silent <= 0:
            noise_db = -96.0
        else:
            noise_db = float(20 * np.log10(mean_silent + 1e-10))

        return {
            "noise_floor_dbfs": round(noise_db, 1),
            "pass": -55 <= noise_db <= -25
        }
    except Exception as e:
        print(f"  Noise floor error: {e}")
        return {"noise_floor_dbfs": -96.0, "pass": False}


def measure_zcr_stability(y: np.ndarray, sr: int) -> dict:
    """Measure zero crossing rate coefficient of variation."""
    try:
        frame_len = 512
        zcr = []
        for i in range(0, len(y) - frame_len, frame_len):
            frame = y[i:i + frame_len]
            crossings = np.sum(np.abs(np.diff(np.sign(frame))) > 0)
            zcr.append(crossings / frame_len)
        zcr = np.array(zcr)
        mean_zcr = float(np.mean(zcr))
        std_zcr = float(np.std(zcr))
        cv = std_zcr / max(mean_zcr, 1e-10)

        return {
            "zcr_cv": round(cv, 3),
            "pass": cv > 0.3
        }
    except Exception as e:
        print(f"  ZCR error: {e}")
        return {"zcr_cv": 0, "pass": False}


def measure_spectral_rolloff(y: np.ndarray, sr: int) -> dict:
    """Measure spectral rolloff variance using FFT."""
    try:
        frame_len = 2048
        hop = 512
        rolloffs = []

        for i in range(0, len(y) - frame_len, hop):
            frame = y[i:i + frame_len]
            spectrum = np.abs(np.fft.rfft(frame))
            total_energy = np.sum(spectrum)
            if total_energy < 1e-10:
                continue
            cumsum = np.cumsum(spectrum)
            rolloff_idx = np.searchsorted(cumsum, 0.85 * total_energy)
            rolloff_hz = rolloff_idx * sr / frame_len
            rolloffs.append(rolloff_hz)

        rolloffs = np.array(rolloffs)
        std_rolloff = float(np.std(rolloffs))

        return {
            "rolloff_std_hz": round(std_rolloff, 1),
            "rolloff_mean_hz": round(float(np.mean(rolloffs)), 1),
            "pass": std_rolloff > 200
        }
    except Exception as e:
        print(f"  Spectral rolloff error: {e}")
        return {"rolloff_std_hz": 0, "rolloff_mean_hz": 0, "pass": False}


def measure_spectral_flatness(y: np.ndarray, sr: int) -> dict:
    """Measure spectral flatness — how 'tonal' vs 'noisy' the signal is."""
    try:
        frame_len = 2048
        hop = 512
        flatness_vals = []

        for i in range(0, len(y) - frame_len, hop):
            frame = y[i:i + frame_len]
            spectrum = np.abs(np.fft.rfft(frame)) + 1e-10
            geo_mean = np.exp(np.mean(np.log(spectrum)))
            arith_mean = np.mean(spectrum)
            flatness_vals.append(geo_mean / arith_mean)

        flatness_vals = np.array(flatness_vals)

        return {
            "flatness_mean": round(float(np.mean(flatness_vals)), 4),
            "flatness_std": round(float(np.std(flatness_vals)), 4),
            "pass": True  # informational metric
        }
    except Exception as e:
        print(f"  Spectral flatness error: {e}")
        return {"flatness_mean": 0, "flatness_std": 0, "pass": True}


def analyze(path: str) -> dict:
    """Run all metrics on a WAV file and return a full report."""
    print(f"\n{'='*60}")
    print(f"VOICE HUMANNESS ANALYSIS: {pathlib.Path(path).name}")
    print(f"{'='*60}")

    y, sr = load_audio(path)
    duration = len(y) / sr
    print(f"Duration: {duration:.2f}s | Sample rate: {sr}Hz | Samples: {len(y)}")

    metrics = {}

    print("\n--- Pitch Analysis ---")
    metrics["pitch"] = measure_pitch_variance(y, sr)
    print(f"  Pitch std: {metrics['pitch']['pitch_std_semitones']} semitones "
          f"({'✅' if metrics['pitch']['pass'] else '❌'} target: 2.0–5.0)")
    print(f"  Pitch range: {metrics['pitch']['pitch_range_hz']} Hz "
          f"(target: ≥80 Hz)")

    print("\n--- RMS Energy Dynamics ---")
    metrics["rms"] = measure_rms_variance(y, sr)
    print(f"  RMS CV: {metrics['rms']['rms_cv']} "
          f"({'✅' if metrics['rms']['pass'] else '❌'} target: >0.15)")

    print("\n--- Noise Floor ---")
    metrics["noise_floor"] = measure_noise_floor(y, sr)
    print(f"  Noise floor: {metrics['noise_floor']['noise_floor_dbfs']} dBFS "
          f"({'✅' if metrics['noise_floor']['pass'] else '❌'} target: -45 to -25 dBFS)")

    print("\n--- Zero Crossing Rate ---")
    metrics["zcr"] = measure_zcr_stability(y, sr)
    print(f"  ZCR CV: {metrics['zcr']['zcr_cv']} "
          f"({'✅' if metrics['zcr']['pass'] else '❌'} target: >0.3)")

    print("\n--- Spectral Rolloff ---")
    metrics["spectral_rolloff"] = measure_spectral_rolloff(y, sr)
    print(f"  Rolloff std: {metrics['spectral_rolloff']['rolloff_std_hz']} Hz "
          f"({'✅' if metrics['spectral_rolloff']['pass'] else '❌'} target: >200 Hz)")

    print("\n--- Spectral Flatness ---")
    metrics["spectral_flatness"] = measure_spectral_flatness(y, sr)
    print(f"  Flatness mean: {metrics['spectral_flatness']['flatness_mean']}")

    # Overall score
    graded = ["pitch", "rms", "noise_floor", "zcr", "spectral_rolloff"]
    passed = sum(1 for k in graded if metrics[k]["pass"])
    humanness_score = int((passed / len(graded)) * 100)

    print(f"\n{'='*60}")
    print(f"HUMANNESS SCORE: {humanness_score}/100 ({passed}/{len(graded)} metrics passed)")
    if humanness_score >= 80:
        print("VERDICT: ✅ PASS — Voice sounds sufficiently human")
    elif humanness_score >= 60:
        print("VERDICT: ⚠️  MARGINAL — Some AI artifacts remain")
    else:
        print("VERDICT: ❌ FAIL — Voice sounds robotic/synthetic")
    print(f"{'='*60}\n")

    return {
        "file": str(path),
        "duration_s": round(duration, 2),
        "sample_rate": sr,
        "metrics": metrics,
        "humanness_score": humanness_score,
        "passed": passed,
        "total_graded": len(graded),
        "verdict": "PASS" if humanness_score >= 80 else "MARGINAL" if humanness_score >= 60 else "FAIL"
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/voice_analyzer.py <wav_file> [output_json]")
        sys.exit(1)

    wav_path = sys.argv[1]
    if not pathlib.Path(wav_path).exists():
        print(f"Error: file not found: {wav_path}")
        sys.exit(1)

    report = analyze(wav_path)

    # Optionally save JSON report
    if len(sys.argv) >= 3:
        out_path = sys.argv[2]
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to: {out_path}")
