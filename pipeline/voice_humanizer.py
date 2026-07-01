# pipeline/voice_humanizer.py — Multi-stage post-processing to humanize TTS output
# 5 stages: time-stretch, pitch jitter, dynamics, room tone + breath, reverb + warmth

import io
import struct
import numpy as np
import pathlib

import config


def _parse_wav_to_array(wav_bytes: bytes) -> tuple:
    """Parse WAV bytes into numpy float32 array + sample rate."""
    import soundfile as sf
    buf = io.BytesIO(wav_bytes)
    data, sr = sf.read(buf, dtype='float32')
    if data.ndim > 1:
        data = data[:, 0]  # mono
    return data, sr


def _array_to_wav(data: np.ndarray, sr: int) -> bytes:
    """Convert numpy float32 array back to WAV bytes."""
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, data, sr, format='WAV', subtype='PCM_16')
    return buf.getvalue()


def stage_time_stretch(audio: np.ndarray, sr: int, speed: float) -> np.ndarray:
    """Stage 1: Proper time-stretching without pitch shift using librosa."""
    try:
        if abs(speed - 1.0) < 0.02:
            return audio
        import librosa
        stretched = librosa.effects.time_stretch(audio, rate=speed)
        print(f"[humanizer] time_stretch: speed={speed:.2f}, {len(audio)} → {len(stretched)} samples")
        return stretched
    except Exception as e:
        print(f"[humanizer] time_stretch error: {e}")
        return audio


def stage_pitch_jitter(audio: np.ndarray, sr: int) -> np.ndarray:
    """Stage 2: Apply micro pitch perturbations to 200ms windows."""
    try:
        import librosa

        jitter_pct = config.TTS.get("humanize_pitch_jitter_pct", 1.0)
        window_samples = int(sr * 0.2)  # 200ms windows
        hop = window_samples // 2  # 50% overlap
        n_samples = len(audio)

        if n_samples < window_samples:
            return audio

        # Create output buffer
        output = np.zeros(n_samples, dtype=np.float32)
        weights = np.zeros(n_samples, dtype=np.float32)
        hann = np.hanning(window_samples).astype(np.float32)

        pos = 0
        while pos + window_samples <= n_samples:
            window = audio[pos:pos + window_samples].copy()

            # Random pitch shift: ±jitter_pct as fraction of semitones
            shift_semitones = np.random.uniform(-jitter_pct * 0.15, jitter_pct * 0.15)

            if abs(shift_semitones) > 0.01:
                window = librosa.effects.pitch_shift(
                    window, sr=sr, n_steps=shift_semitones
                )
                # Ensure same length
                if len(window) > window_samples:
                    window = window[:window_samples]
                elif len(window) < window_samples:
                    window = np.pad(window, (0, window_samples - len(window)))

            # Apply Hann window and overlap-add
            output[pos:pos + window_samples] += window * hann
            weights[pos:pos + window_samples] += hann

            pos += hop

        # Normalize by overlap weights
        mask = weights > 1e-8
        output[mask] /= weights[mask]
        # Copy any remaining tail
        if pos < n_samples:
            output[pos:] = audio[pos:]

        print(f"[humanizer] pitch_jitter: ±{jitter_pct}% applied across {pos // hop} windows")
        return output
    except Exception as e:
        print(f"[humanizer] pitch_jitter error: {e}")
        return audio


def stage_dynamics(audio: np.ndarray, sr: int, word_timings: list[dict] = None) -> np.ndarray:
    """Stage 3: Word-level volume variation + gentle compression."""
    try:
        import librosa

        # Use actual word boundaries if available, else fallback to librosa onsets
        if word_timings:
            onsets = [int(w["start"] * sr) for w in word_timings] + [len(audio)]
        else:
            onsets = librosa.onset.onset_detect(y=audio, sr=sr, hop_length=512, units='samples')

        if len(onsets) < 2:
            print("[humanizer] dynamics: too few onsets, skipping word-level variation")
        else:
            # Apply subtle random gain per segment
            for i in range(len(onsets) - 1):
                start = onsets[i]
                end = onsets[i + 1]
                gain_db = np.random.uniform(-1.5, 1.5)
                gain_linear = 10 ** (gain_db / 20.0)
                audio[start:end] *= gain_linear

        # Gentle compression
        threshold_db = config.TTS.get("humanize_compression_threshold_db", -18)
        ratio = config.TTS.get("humanize_compression_ratio", 2.0)
        threshold_linear = 10 ** (threshold_db / 20.0)

        # Frame-by-frame compression
        frame_len = 512
        for i in range(0, len(audio) - frame_len, frame_len):
            frame = audio[i:i + frame_len]
            rms = np.sqrt(np.mean(frame ** 2))
            if rms > threshold_linear:
                # Calculate gain reduction
                excess_db = 20 * np.log10(rms / threshold_linear + 1e-10)
                reduction_db = excess_db * (1 - 1 / ratio)
                gain = 10 ** (-reduction_db / 20.0)
                audio[i:i + frame_len] *= gain

        print(f"[humanizer] dynamics: {len(onsets)} segments, compression at {threshold_db}dB/{ratio}:1")
        return audio
    except Exception as e:
        print(f"[humanizer] dynamics error: {e}")
        return audio


def _generate_breath(sr: int, duration_ms: int = 200) -> np.ndarray:
    """Generate a synthetic breath sound using filtered pink noise."""
    try:
        n_samples = int(sr * duration_ms / 1000)

        # Generate pink noise (1/f spectrum)
        white = np.random.randn(n_samples).astype(np.float32)

        # Simple 1/f filter using cumulative sum with decay
        pink = np.zeros(n_samples, dtype=np.float32)
        b = [0.049922035, -0.095993537, 0.050612699, -0.004709510]
        buf = [0.0] * len(b)
        for i in range(n_samples):
            buf_sum = sum(b[j] * buf[j] for j in range(len(b)))
            pink[i] = white[i] + buf_sum
            buf = [white[i]] + buf[:-1]

        # Bandpass 200-2000Hz using simple FFT filter
        freqs = np.fft.rfftfreq(n_samples, 1.0 / sr)
        fft = np.fft.rfft(pink)
        mask = np.zeros_like(freqs)
        mask[(freqs >= 200) & (freqs <= 2000)] = 1.0
        # Smooth edges
        fft *= mask
        pink = np.fft.irfft(fft, n=n_samples).astype(np.float32)

        # Apply envelope (fade in/out)
        envelope = np.ones(n_samples, dtype=np.float32)
        fade_samples = int(n_samples * 0.15)
        envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
        envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
        pink *= envelope

        # Normalize
        peak = np.max(np.abs(pink))
        if peak > 0:
            pink /= peak

        return pink
    except Exception as e:
        print(f"[humanizer] breath generation error: {e}")
        return np.zeros(int(sr * 0.2), dtype=np.float32)


def stage_room_tone_and_breath(audio: np.ndarray, sr: int, word_timings: list[dict] = None) -> np.ndarray:
    """Stage 4: Add room tone underneath + inject breath sounds in silent gaps."""
    try:
        import librosa

        room_tone_db = config.TTS.get("humanize_room_tone_db", -42)
        breath_db = config.TTS.get("humanize_breath_db", -30)

        # Generate Brownian noise for room tone
        white = np.random.randn(len(audio)).astype(np.float32)
        brownian = np.cumsum(white)
        # Normalize and set level
        brownian = brownian / (np.max(np.abs(brownian)) + 1e-10)
        room_level = 10 ** (room_tone_db / 20.0)
        room_tone = brownian * room_level

        # Mix room tone under audio
        audio = audio + room_tone

        # Find silent gaps (RMS below threshold) and inject breaths
        rms = librosa.feature.rms(y=audio, hop_length=512)[0]
        threshold = np.percentile(rms, 15)
        breath_sound = _generate_breath(sr, duration_ms=180)
        breath_level = 10 ** (breath_db / 20.0)
        breath_sound *= breath_level

        # Find gap positions
        breaths_injected = 0
        min_gap_frames = int(0.15 * sr / 512)  # at least 150ms gap
        in_gap = False
        gap_start = 0

        # Build an exclusion mask based on exact word_timings to avoid breathing inside a word
        exclusion_mask = np.zeros_like(rms, dtype=bool)
        if word_timings:
            for w in word_timings:
                s_frame = int(w["start"] * sr / 512)
                e_frame = int(w["end"] * sr / 512)
                exclusion_mask[s_frame:e_frame] = True

        for i in range(len(rms)):
            # Force threshold check to fail if we are inside a word
            is_silent = (rms[i] <= threshold) and not exclusion_mask[i]
            
            if is_silent:
                if not in_gap:
                    gap_start = i
                    in_gap = True
            else:
                if in_gap and (i - gap_start) >= min_gap_frames:
                    # Inject breath in middle of gap
                    mid_sample = ((gap_start + i) // 2) * 512
                    end_sample = min(mid_sample + len(breath_sound), len(audio))
                    breath_len = end_sample - mid_sample
                    if breath_len > 0 and breaths_injected < 3:
                        audio[mid_sample:end_sample] += breath_sound[:breath_len]
                        breaths_injected += 1
                in_gap = False

        print(f"[humanizer] room_tone: {room_tone_db}dB brownian | {breaths_injected} breaths injected at {breath_db}dB")
        return audio
    except Exception as e:
        print(f"[humanizer] room_tone_breath error: {e}")
        return audio


def stage_reverb_and_warmth(audio: np.ndarray, sr: int) -> np.ndarray:
    """Stage 5: Subtle room reverb + EQ warmth."""
    try:
        from scipy import signal as sig

        # --- Tiny room reverb (RT60 ≈ 0.1s) ---
        rt60 = config.TTS.get("humanize_reverb_rt60", 0.1)
        ir_length = int(sr * rt60)
        # Generate simple exponential decay impulse response
        ir = np.random.randn(ir_length).astype(np.float32)
        decay = np.exp(-np.linspace(0, 6, ir_length))  # 60dB decay
        ir *= decay
        ir[0] = 1.0  # direct sound
        ir /= np.sum(np.abs(ir))  # normalize energy

        # Convolve (wet signal)
        wet = np.convolve(audio, ir, mode='full')[:len(audio)]
        # Mix: 85% dry + 15% wet
        audio = 0.85 * audio + 0.15 * wet

        # --- High-shelf cut above 12kHz ---
        high_cut_db = config.TTS.get("humanize_high_shelf_cut_db", -2)
        if sr > 24000:  # Only if sample rate supports it
            nyq = sr / 2
            cutoff = min(12000 / nyq, 0.95)
            b, a = sig.butter(2, cutoff, btype='low')
            high_filtered = sig.lfilter(b, a, audio)
            # Blend: mix based on dB cut
            mix = 1.0 - (10 ** (high_cut_db / 20.0))
            audio = (1 - mix) * audio + mix * high_filtered

        # --- Low-shelf boost at 150Hz ---
        low_boost_db = config.TTS.get("humanize_low_shelf_boost_db", 1.5)
        nyq = sr / 2
        low_cutoff = min(150 / nyq, 0.95)
        b_low, a_low = sig.butter(2, low_cutoff, btype='low')
        low_content = sig.lfilter(b_low, a_low, audio)
        boost = 10 ** (low_boost_db / 20.0) - 1.0
        audio = audio + boost * low_content

        # Final peak normalization to -1dBFS
        peak = np.max(np.abs(audio))
        if peak > 0:
            target = 10 ** (-1 / 20.0)  # -1 dBFS
            audio = audio * (target / peak)

        print(f"[humanizer] reverb: RT60={rt60}s, high_cut={high_cut_db}dB, low_boost={low_boost_db}dB")
        return audio
    except Exception as e:
        print(f"[humanizer] reverb_warmth error: {e}")
        return audio


def rescale_word_timings(word_timings: list[dict], speed: float) -> list[dict]:
    """Rescale timings when audio is time-stretched."""
    if not word_timings or abs(speed - 1.0) < 0.02:
        return word_timings
    
    # When speed is e.g. 1.25, the audio is 25% faster and durations are shorter.
    # New timestamp = old timestamp / speed
    rescaled = []
    for w in word_timings:
        rescaled.append({
            "word": w["word"],
            "start": w["start"] / speed,
            "end": w["end"] / speed
        })
    return rescaled


def diagnose_word_gaps(word_timings: list[dict]) -> None:
    """Log the distribution of gaps between words."""
    if not word_timings or len(word_timings) < 2:
        return
        
    gaps = []
    for i in range(1, len(word_timings)):
        gap = word_timings[i]["start"] - word_timings[i-1]["end"]
        if gap > 0:
            gaps.append(gap)
            
    if gaps:
        print(f"[humanizer] timing gaps: min={min(gaps):.3f}s, max={max(gaps):.3f}s, avg={sum(gaps)/len(gaps):.3f}s ({len(gaps)} total)")


def humanize(wav_bytes: bytes, speed: float = 1.0, word_timings: list[dict] = None) -> tuple[bytes, list[dict]]:
    """
    Run full humanization post-processing pipeline on an audio buffer.
    
    Stages:
    1. Time stretch (preserves pitch)
    2. Micro pitch jitter
    3. Dynamic range humanization
    4. Room tone + breath injection
    5. Reverb + warmth EQ
    """
    try:
        audio, sr = _parse_wav_to_array(wav_bytes)
        print(f"[humanizer] input: {len(audio)} samples, {sr}Hz, {len(audio)/sr:.2f}s")

        # Stage 1: Time stretch
        audio = stage_time_stretch(audio, sr, speed)
        
        # Rescale word timings after stretch
        if word_timings:
            word_timings = rescale_word_timings(word_timings, speed)
            diagnose_word_gaps(word_timings)

        # Stage 2: Pitch jitter
        audio = stage_pitch_jitter(audio, sr)

        # Stage 3: Dynamics
        audio = stage_dynamics(audio, sr, word_timings)

        # Stage 4: Room tone + breaths
        audio = stage_room_tone_and_breath(audio, sr, word_timings)

        # Stage 5: Reverb + warmth
        audio = stage_reverb_and_warmth(audio, sr)

        result = _array_to_wav(audio, sr)
        print(f"[humanizer] output: {len(result)} bytes WAV")
        return result, word_timings or []
    except Exception as e:
        print(f"[humanizer] error: {e}")
        return wav_bytes, word_timings or []


def humanize_file(input_path: str, output_path: str, speed: float = 1.0) -> bool:
    """Humanize a WAV file on disk."""
    try:
        with open(input_path, "rb") as f:
            wav_bytes = f.read()

        result_bytes, _ = humanize(wav_bytes, speed)

        with open(output_path, "wb") as f:
            f.write(result_bytes)

        print(f"[humanizer] saved: {output_path}")
        return True
    except Exception as e:
        print(f"[humanizer] file error: {e}")
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        speed = float(sys.argv[3]) if len(sys.argv) >= 4 else 1.0
        humanize_file(sys.argv[1], sys.argv[2], speed)
    else:
        print("Usage: python -m pipeline.voice_humanizer <input.wav> <output.wav> [speed]")
