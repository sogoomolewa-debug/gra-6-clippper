import os
import time
from google import genai
from pydantic import BaseModel, Field

class VideoAnalysis(BaseModel):
    is_gameplay: bool
    is_punchy: bool
    punchiness_reasoning: str
    description: str
    natural_start: float
    natural_end: float

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

video_path = "scratch/raw_segment.mp4"
print(f"Uploading {video_path}...")
video_file = client.files.upload(file=video_path)

while True:
    file_info = client.files.get(name=video_file.name)
    if file_info.state.name == "ACTIVE":
        break
    time.sleep(3)

print(f"File active. Running gemini-2.5-pro...")
peak_sec_local = 30.0
comment_context = "2:18"

prompt = (
    f"This is a clip from a video related to Grand Theft Auto. "
    f"A viewer left this comment about what happens at {peak_sec_local:.0f} seconds: '{comment_context}'. "
    f"Perform the following analysis tasks:\n"
    f"1. Determine if this clip shows actual, direct in-game gameplay graphics of a GTA game being played. If it is a talking head, news/speculation slides, podcast, commentary show, or reaction video with minimal gameplay, set is_gameplay to false.\n"
    f"2. Determine if the moment is 'punchy'. Can this moment be fully understood, enjoyed, and impactful in under 15 seconds? If it requires a long buildup or extended context to make sense (e.g., a 40-second conversation or a long chase), set is_punchy to false. We only want fast, punchy action or immediate comedy.\n"
    f"3. Describe in exactly ONE sentence what visually happens at {peak_sec_local:.0f} seconds.\n"
    f"4. Find where the peak action at {peak_sec_local:.0f} seconds naturally begins (setup) and naturally ends (reaction complete). "
    f"Requirements: window must be 10-14 seconds long — just the core moment, tight and punchy, no buildup, no aftermath. Peak at {peak_sec_local:.0f}s must be inside the window."
)

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=[video_file, prompt],
    config={
        "response_mime_type": "application/json",
        "response_schema": VideoAnalysis,
        "temperature": 0.2
    }
)

print(response.text)
client.files.delete(name=video_file.name)
