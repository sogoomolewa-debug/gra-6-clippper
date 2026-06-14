# modal_tts.py — Deploy Qwen3-TTS on Modal GPU

import modal
import base64
import io

app = modal.App("qwen3-tts")
volume = modal.Volume.from_name("qwen3-tts-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install([
        "qwen-tts",
        "soundfile",
        "torch",
        "transformers<5.0",
        "numpy",
        "accelerate"
    ])
)

@app.function(
    image=image,
    gpu="A10G",
    volumes={"/model-cache": volume},
    timeout=120,
    scaledown_window=60
)
@modal.fastapi_endpoint(method="POST")
def generate(request: dict) -> dict:
    """Generate voice clone audio from text and reference audio."""
    try:
        import torch
        import soundfile as sf
        import numpy as np
        import os
        from qwen_tts import Qwen3TTSModel

        os.environ["HF_HOME"] = "/model-cache"

        # Load model (cached in volume)
        print("[modal] loading model (1.7B)...")
        model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            device_map="cuda",
            torch_dtype=torch.bfloat16
        )

        # Decode reference audio
        ref_audio_b64 = request.get("ref_audio_b64", "")
        if not ref_audio_b64:
            return {"error": "Missing ref_audio_b64"}
        
        ref_path = "/tmp/ref.wav"
        with open(ref_path, "wb") as f:
            f.write(base64.b64decode(ref_audio_b64))

        # Generate audio
        print(f"[modal] synthesizing: {request.get('text', '')}")
        # The model returns (wavs, sr)
        # wavs is usually a list of arrays or a single array/tensor
        result = model.generate_voice_clone(
            text=request["text"],
            ref_audio=ref_path,
            ref_text=request["ref_text"]
        )
        
        if isinstance(result, tuple) and len(result) == 2:
            wavs, sr = result
        else:
            # Fallback for unexpected return format
            wavs = result
            sr = 24000
            
        print(f"[modal] synthesis raw type: {type(wavs)}")
        
        # Handle list, tensor, or array
        if isinstance(wavs, (list, tuple)):
            print(f"[modal] processing {len(wavs)} segments")
            processed = []
            for w in wavs:
                if torch.is_tensor(w):
                    processed.append(w.detach().cpu().numpy().flatten())
                else:
                    processed.append(np.array(w).flatten())
            final_wav = np.concatenate(processed)
        elif torch.is_tensor(wavs):
            final_wav = wavs.detach().cpu().numpy().flatten()
        else:
            final_wav = np.array(wavs).flatten()
        
        print(f"[modal] final audio shape: {final_wav.shape}, sr: {sr}")

        # Apply speed adjustment via linear interpolation (time-stretching)
        speed = float(request.get("speed", 1.0))
        speed = max(0.5, min(2.0, speed))  # clamp to safe range
        if abs(speed - 1.0) > 0.01:
            original_len = len(final_wav)
            new_len = int(original_len / speed)
            indices = np.linspace(0, original_len - 1, new_len)
            final_wav = np.interp(indices, np.arange(original_len), final_wav)
            print(f"[modal] speed={speed:.2f}: {original_len} → {new_len} samples")

        # Write to temporary WAV file
        out_path = "/tmp/out.wav"
        sf.write(out_path, final_wav, sr, format="WAV", subtype="PCM_16")
        
        with open(out_path, "rb") as f:
            audio_bytes = f.read()
        
        return {
            "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
            "sample_rate": sr
        }
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[modal] error: {error_msg}")
        return {"error": error_msg}

# Deploy with: modal deploy modal_tts.py
