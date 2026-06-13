# pipeline/voice.py — Send hook text to Modal endpoint, receive synthesized WAV audio

import os
import pathlib
import base64

import requests

import config


def generate_voice(text: str, output_path: str) -> bool:
    """Generate voice audio via Modal TTS endpoint."""
    try:
        endpoint = os.environ.get("MODAL_TTS_ENDPOINT", "")
        if not endpoint:
            print("[voice] error: MODAL_TTS_ENDPOINT not set")
            return False

        ref_text = os.environ.get("REF_TEXT", "")
        if not ref_text:
            print("[voice] error: REF_TEXT not set")
            return False

        voice_sample = pathlib.Path(config.TTS["voice_sample_path"])
        if not voice_sample.exists():
            print(f"[voice] error: voice sample not found at {voice_sample}")
            return False

        # Read and base64-encode voice sample
        print(f"[voice] reading voice sample: {voice_sample}")
        with open(voice_sample, "rb") as f:
            audio_bytes = f.read()
        encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")

        # POST to Modal endpoint
        print(f"[voice] sending to Modal endpoint: {endpoint}")
        payload = {
            "text": text,
            "ref_audio_b64": encoded_audio,
            "ref_text": ref_text
        }
        response = requests.post(
            endpoint,
            json=payload,
            timeout=config.TTS["modal_timeout_seconds"]
        )

        if response.status_code != 200:
            print(f"[voice] error: HTTP {response.status_code} — {response.text[:200]}")
            return False

        response_data = response.json()
        if "error" in response_data:
            print(f"[voice] endpoint error: {response_data['error']}")
            return False

        # Decode audio from response
        audio_b64 = response_data.get("audio_b64", "")
        if not audio_b64:
            print("[voice] error: no audio_b64 in response")
            return False

        audio_data = base64.b64decode(audio_b64)

        # Write to output path
        output = pathlib.Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as f:
            f.write(audio_data)

        # Verify output
        if not output.exists() or output.stat().st_size < 1000:
            print(f"[voice] error: output file too small or missing ({output})")
            return False

        print(f"[voice] synthesized {len(text)} chars → {output_path} ({output.stat().st_size} bytes)")
        return True
    except requests.Timeout:
        print("[voice] error: request timed out")
        return False
    except Exception as e:
        print(f"[voice] error: {e}")
        return False


if __name__ == "__main__":
    result = generate_voice("Nobody saw this coming.", "/tmp/test_hook.wav")
    print(f"Voice generation result: {result}")
