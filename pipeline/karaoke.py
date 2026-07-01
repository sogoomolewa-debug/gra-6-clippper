# pipeline/karaoke.py — PIL-based karaoke caption frame generator
# Produces a series of transparent PNGs + an ffmpeg concat file
# for word-by-word highlight overlays.

import os
from PIL import Image, ImageDraw, ImageFont


def create_karaoke_concat(
    word_timings: list[dict],
    emphasis_word: str,
    font_path: str,
    fontsize: int,
    tmp_dir: str,
    video_duration: float,
    cycle_enabled: bool = False,
    cycle_colors: list[str] = None
) -> str:
    """Generate karaoke caption frames and return path to ffmpeg concat file.

    Each frame shows all words with one word highlighted (yellow or orange
    for the emphasis word).  The concat file sequences frames so each word
    lights up in sync with its Whisper timing.
    """
    # Canvas matches 9:16 vertical short
    W, H = 1080, 1920
    font = ImageFont.truetype(font_path, fontsize)
    emphasis_font = ImageFont.truetype(font_path, int(fontsize * 1.15))

    margin = 80
    max_w = W - margin * 2

    # ── Layout: measure words in UPPERCASE (since we draw uppercase) ──
    space_w = font.getbbox(" ")[2]
    words_upper = [w["word"].upper() for w in word_timings]

    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_x = 0

    for i, w in enumerate(words_upper):
        bbox = font.getbbox(w)
        w_w = bbox[2] - bbox[0]
        if current_line and current_x + w_w > max_w:
            lines.append(current_line)
            current_line = []
            current_x = 0
        current_line.append({"text": w, "idx": i, "w": w_w})
        current_x += w_w + space_w
    if current_line:
        lines.append(current_line)

    line_h = font.getbbox("A")[3] * 1.3
    total_h = len(lines) * line_h
    start_y = (H - total_h) / 2

    # ── Calculate exact centred positions ──
    positions: dict[int, tuple[float, float]] = {}
    y = start_y
    for line in lines:
        line_w = sum(item["w"] for item in line) + space_w * (len(line) - 1)
        x = (W - line_w) / 2
        for item in line:
            positions[item["idx"]] = (x, y)
            x += item["w"] + space_w
        y += line_h

    # ── Colours ──
    base_color = "white"
    karaoke_color = "yellow"
    emp_color = "#FF6B35"
    outline_color = "black"
    outline_w = 6

    def draw_text_outlined(d: ImageDraw.ImageDraw, pos, text, fill, fnt):
        x, y = pos
        # Outline
        for dx in range(-outline_w, outline_w + 1, 2):
            for dy in range(-outline_w, outline_w + 1, 2):
                d.text((x + dx, y + dy), text, font=fnt, fill=outline_color)
        # Shadow
        d.text((x + 3, y + 3), text, font=fnt, fill="black")
        # Fill
        d.text((x, y), text, font=fnt, fill=fill)

    # ── Generate one PNG per word-state (-1 = no highlight) ──
    emphasis_upper = emphasis_word.upper() if emphasis_word else ""

    for active_idx in range(-1, len(words_upper)):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        for idx, word_text in enumerate(words_upper):
            is_active = (idx == active_idx)
            is_emp = (word_text == emphasis_upper and emphasis_upper != "")

            fnt = emphasis_font if (is_emp and is_active) else font
            color = base_color
            if is_active:
                if is_emp:
                    color = emp_color
                elif cycle_enabled and cycle_colors:
                    color = cycle_colors[idx % len(cycle_colors)]
                else:
                    color = karaoke_color

            pos = positions[idx]
            # Re-centre if using the larger emphasis font
            if fnt != font:
                bbox_n = fnt.getbbox(word_text)
                bbox_o = font.getbbox(word_text)
                dx = ((bbox_o[2] - bbox_o[0]) - (bbox_n[2] - bbox_n[0])) / 2
                dy = ((bbox_o[3] - bbox_o[1]) - (bbox_n[3] - bbox_n[1])) / 2
                pos = (pos[0] + dx, pos[1] + dy)

            draw_text_outlined(d, pos, word_text, color, fnt)

        out_path = os.path.join(tmp_dir, f"state_{active_idx}.png")
        img.save(out_path)

    # ── Build ffmpeg concat file (absolute paths) ──
    no_highlight = os.path.join(tmp_dir, "state_-1.png")

    concat_path = os.path.join(tmp_dir, "karaoke_concat.txt")
    with open(concat_path, "w") as f:
        # Silence before first word
        first_start = word_timings[0]["start"] if word_timings else 0
        if first_start > 0:
            f.write(f"file '{no_highlight}'\nduration {first_start:.3f}\n")

        for i, w in enumerate(word_timings):
            dur = w["end"] - w["start"]
            frame_path = os.path.join(tmp_dir, f"state_{i}.png")
            f.write(f"file '{frame_path}'\nduration {dur:.3f}\n")

            # Gap to next word — show no-highlight frame
            if i < len(word_timings) - 1:
                gap = word_timings[i + 1]["start"] - w["end"]
                if gap > 0:
                    f.write(f"file '{no_highlight}'\nduration {gap:.3f}\n")

        # Tail after last word
        last_end = word_timings[-1]["end"] if word_timings else 0
        if last_end < video_duration:
            f.write(f"file '{no_highlight}'\nduration {video_duration - last_end:.3f}\n")

    return concat_path
