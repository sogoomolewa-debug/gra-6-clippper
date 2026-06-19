# modal_video.py — Deploy Qwen2.5-VL-7B-Instruct on Modal GPU
import modal
import base64
import io
import os
import tempfile
import pathlib

app = modal.App("qwen-video-analyzer")

volume = modal.Volume.from_name("qwen-video-weights", create_if_missing=True)

# Separate volume from TTS — different model weights
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(["ffmpeg", "libgl1"])
    .pip_install([
        "torch",
        "torchvision",
        "transformers>=4.45.0",
        "qwen-vl-utils",
        "accelerate",
        "av",
        "Pillow",
        "numpy",
        "fastapi[standard]",
        "decord"
    ])
)

@app.function(
    image=image,
    gpu="A10G",
    volumes={"/model-cache": volume},
    timeout=180,
    scaledown_window=60
)
@modal.fastapi_endpoint(method="POST")
def analyze_clip(request: dict) -> dict:
    """
    Input:
    {
        "video_b64": str,          # base64 encoded mp4 segment
        "peak_sec_local": float,   # peak timestamp within THIS segment (not global)
        "segment_duration": float, # total duration of the segment in seconds
        "comment_context": str     # viewer comment describing the viral moment
    }
    Output:
    {
      "description": str,        # one sentence describing what happens at peak
      "natural_start": float,    # seconds into segment where action begins
      "natural_end": float,      # seconds into segment where action ends
      "error": str | None
    }
    """
    import torch
    import re
    import shutil
    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
    from qwen_vl_utils import process_vision_info

    os.environ["HF_HOME"] = "/model-cache"
    os.environ["FORCE_QWENVL_VIDEO_READER"] = "decord"

    # Decode and save video to temp file
    video_bytes = base64.b64decode(request["video_b64"])
    tmp_dir = tempfile.mkdtemp()
    video_path = pathlib.Path(tmp_dir) / "segment.mp4"
    video_path.write_bytes(video_bytes)

    peak_local = float(request["peak_sec_local"])
    segment_dur = float(request["segment_duration"])
    comment_context = request.get("comment_context", "an interesting gameplay moment")

    try:
        # Load model
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            "Qwen/Qwen2.5-VL-7B-Instruct",
            torch_dtype=torch.bfloat16,
            device_map="cuda"
        )
        processor = AutoProcessor.from_pretrained(
            "Qwen/Qwen2.5-VL-7B-Instruct",
            min_pixels=256*28*28,
            max_pixels=512*28*28
        )

        # --- QUESTION 1: Describe the peak moment (guided by comment context) ---
        q1_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video",
                        "video": str(video_path),
                        "fps": 2.0,                          # 2 frames/sec — enough detail
                        "max_frames": 64
                    },
                    {
                        "type": "text",
                        "text": (
                            f"This is a GTA 6 gameplay video segment. "
                            f"At approximately {peak_local:.0f} seconds into this clip, "
                            f"viewers left this comment: '{comment_context}'. "
                            f"Based on that comment, describe in ONE sentence exactly what visually "
                            f"happens at that specific timestamp. "
                            f"Focus ONLY on that moment — ignore everything else in the clip."
                        )
                    }
                ]
            }
        ]

        text_q1 = processor.apply_chat_template(
            q1_messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(q1_messages)
        inputs_q1 = processor(
            text=[text_q1],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        ).to("cuda")

        with torch.no_grad():
            out_q1 = model.generate(**inputs_q1, max_new_tokens=80)
        description = processor.decode(
            out_q1[0][inputs_q1.input_ids.shape[1]:],
            skip_special_tokens=True
        ).strip()

        # --- QUESTION 2: Find natural boundaries (guided by comment context) ---
        q2_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video",
                        "video": str(video_path),
                        "fps": 2.0,
                        "max_frames": 64
                    },
                    {
                        "type": "text",
                        "text": (
                            f"This GTA 6 gameplay clip is {segment_dur:.0f} seconds long. "
                            f"A viewer described this moment at {peak_local:.0f} seconds: '{comment_context}'. "
                            f"Find where this specific action NATURALLY BEGINS (the setup before it) "
                            f"and where it NATURALLY ENDS (after the full reaction plays out). "
                            f"Reply with ONLY two numbers separated by a comma: start_second,end_second. "
                            f"The window must be between 45 and 55 seconds long. "
                            f"The peak moment at {peak_local:.0f}s must be INSIDE the window. "
                            f"Do not explain. Just two numbers."
                        )
                    }
                ]
            }
        ]

        text_q2 = processor.apply_chat_template(
            q2_messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs2, video_inputs2 = process_vision_info(q2_messages)
        inputs_q2 = processor(
            text=[text_q2],
            images=image_inputs2,
            videos=video_inputs2,
            padding=True,
            return_tensors="pt"
        ).to("cuda")

        with torch.no_grad():
            out_q2 = model.generate(**inputs_q2, max_new_tokens=20)
        boundary_text = processor.decode(
            out_q2[0][inputs_q2.input_ids.shape[1]:],
            skip_special_tokens=True
        ).strip()

        # Parse boundaries
        numbers = re.findall(r'\d+\.?\d*', boundary_text)
        if len(numbers) >= 2:
            natural_start = float(numbers[0])
            natural_end = float(numbers[1])

            # Validate: clip must be 45-55 seconds, within segment
            clip_len = natural_end - natural_start
            if clip_len < 45 or clip_len > 55 or natural_end > segment_dur:
                # Fallback to smart offset around peak
                natural_start = max(0.0, peak_local - 8.0)
                natural_end = natural_start + 52.0
        else:
            natural_start = max(0.0, peak_local - 8.0)
            natural_end = natural_start + 52.0

        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return {
            "description": description,
            "natural_start": round(natural_start, 1),
            "natural_end": round(natural_end, 1),
            "error": None
        }

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {
            "description": "",
            "natural_start": max(0.0, peak_local - 8.0),
            "natural_end": max(0.0, peak_local - 8.0) + 52.0,
            "error": str(e)
        }
