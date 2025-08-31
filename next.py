# filename: live_news_urdu.py
import os
import time
import subprocess
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import feedparser
from gtts import gTTS
import arabic_reshaper
from bidi.algorithm import get_display
from deep_translator import GoogleTranslator

# =========================
# User Configuration
# =========================
STREAM_KEY = "tcdq-j0as-rebb-yq2k-2rbv"
YT_RTMP_URL = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

# Add your 10 RSS feeds here (examples; replace with your own)
FEEDS = [
    "https://www.bbc.com/urdu/index.xml",
    "https://feeds.dawn.com/dawn-news",
    "https://www.geo.tv/rss/1/1",
    "https://www.thenews.com.pk/rss/1/1",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.reuters.com/world/rss",
    "https://rss.cnn.com/rss/edition_world.rss",
    "https://www.aa.com.tr/en/rss/default?cat=news",
    "https://www.voanews.com/rss",
    "https://feeds.skynews.com/feeds/rss/world.xml",
]

# Video settings
WIDTH, HEIGHT = 1920, 1080
FPS = 24
BITRATE = "4500k"
GOP = FPS * 2

# Visual layout
TICKER_HEIGHT = 90
TICKER_BG = (200, 0, 0, 255)            # Red ticker
TICKER_TEXT_COLOR = (255, 255, 255, 255)
TICKER_SPEED_PX_PER_SEC = 160
TICKER_GAP = 140
ANCHOR_POS = (40, 180)                  # top-left position of anchor overlay
ANCHOR_MAX_WIDTH = 520

# Cycle settings
CYCLE_DURATION_SEC = 600                # 10 minutes per cycle

# Assets
STUDIO_BG = "studio.jpg"
ANCHOR_IMG = "anchor.png"
URDU_TTF = "Urdu.ttf"
TTS_FILE = "tts.mp3"

# =========================
# Helpers
# =========================

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        raise EnvironmentError("FFmpeg نہیں ملا۔ پہلے FFmpeg انسٹال کریں اور PATH میں شامل کریں۔")

def ensure_assets():
    missing = [p for p in [STUDIO_BG, ANCHOR_IMG, URDU_TTF] if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(f"ضروری فائلیں غائب ہیں: {missing}. انہی ناموں کے ساتھ اسی فولڈر میں رکھیں۔")

def fetch_headlines(max_items=40):
    items, seen = [], set()
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = (entry.get("title") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append(title)
                if len(items) >= max_items:
                    return items
        except Exception:
            continue
    return items

def to_urdu(text):
    try:
        return GoogleTranslator(source="auto", target="ur").translate(text)
    except Exception:
        return text  # fallback

def shape_urdu(text):
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def make_ticker_text(headlines_ur):
    sep = "  —  "
    base = sep.join(headlines_ur)
    if len(base) < 40:
        base = (base + sep) * 6
    return base

def make_tts(headlines_ur, out_path=TTS_FILE):
    numbered = [f"خبر نمبر {i+1}: {h}." for i, h in enumerate(headlines_ur[:20])]
    script = "  ".join(numbered)
    tts = gTTS(text=script, lang="ur", slow=False)
    tts.save(out_path)
    return out_path

def load_images():
    bg = Image.open(STUDIO_BG).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    anchor = Image.open(ANCHOR_IMG).convert("RGBA")
    if anchor.width > ANCHOR_MAX_WIDTH:
        scale = ANCHOR_MAX_WIDTH / anchor.width
        anchor = anchor.resize((int(anchor.width*scale), int(anchor.height*scale)), Image.LANCZOS)
    return bg, anchor

def build_static_base(bg_img, anchor_img):
    frame = bg_img.copy()
    frame.paste(anchor_img, ANCHOR_POS, anchor_img)
    return frame

def build_ticker_strip(ticker_text, font):
    shaped = shape_urdu(ticker_text)
    tmp = Image.new("RGBA", (10, 10), (0,0,0,0))
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0,0), shaped, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    strip_h = TICKER_HEIGHT
    strip_w = text_w + TICKER_GAP + text_w
    strip = Image.new("RGBA", (strip_w, strip_h), TICKER_BG)
    draw = ImageDraw.Draw(strip)
    y = (strip_h - text_h) // 2 - 2
    draw.text((0, y), shaped, font=font, fill=TICKER_TEXT_COLOR)
    draw.text((text_w + TICKER_GAP, y), shaped, font=font, fill=TICKER_TEXT_COLOR)
    return strip, strip_w, strip_h

def ffmpeg_process(audio_file):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-re",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "-",
        "-stream_loop", "-1",
        "-i", audio_file,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", BITRATE,
        "-pix_fmt", "yuv420p",
        "-g", str(GOP),
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-f", "flv",
        YT_RTMP_URL
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, bufsize=10**7)

def run_cycle(base_frame_rgb, ticker_strip, strip_w, strip_h, duration_sec):
    proc = ffmpeg_process(TTS_FILE)
    start = time.time()
    ticker_y = HEIGHT - TICKER_HEIGHT
    base_np = np.array(base_frame_rgb)
    px_per_frame = TICKER_SPEED_PX_PER_SEC / FPS
    frame_idx = 0
    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= duration_sec:
                break
            offset = int((elapsed * TICKER_SPEED_PX_PER_SEC) % strip_w)
            frame = Image.fromarray(base_np.copy())
            window = Image.new("RGBA", (WIDTH, TICKER_HEIGHT), TICKER_BG)
            if offset + WIDTH <= strip_w:
                crop = ticker_strip.crop((offset, 0, offset + WIDTH, strip_h))
                window.paste(crop, (0, 0))
            else:
                first = ticker_strip.crop((offset, 0, strip_w, strip_h))
                second_width = WIDTH - (strip_w - offset)
                second = ticker_strip.crop((0, 0, second_width, strip_h))
                window.paste(first, (0, 0))
                window.paste(second, (first.width, 0))
            frame.paste(window, (0, ticker_y), window)
            rgb = frame.convert("RGB")
            proc.stdin.write(rgb.tobytes())
            frame_idx += 1
            target = frame_idx / FPS
            ahead = target - (time.time() - start)
            if ahead > 0:
                time.sleep(min(ahead, 0.02))
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

def main():
    check_ffmpeg()
    ensure_assets()
    bg, anchor = load_images()
    base = build_static_base(bg, anchor)
    base_rgb = base.convert("RGB")
    font = ImageFont.truetype(URDU_TTF, 46)

    print("Urdu Live News streaming to YouTube...")
    while True:
        raw = fetch_headlines(max_items=40)
        if not raw:
            raw = ["اس وقت کوئی خبر دستیاب نہیں۔ براہ کرم کچھ دیر بعد ملاحظہ کریں۔"]
        ur_list, translated = [], 0
        for t in raw:
            try:
                u = to_urdu(t)
                ur_list.append(u)
                translated += 1
            except Exception:
                ur_list.append(t)
        ticker_text = make_ticker_text(ur_list)
        make_tts(ur_list, TTS_FILE)
        ticker_strip, strip_w, strip_h = build_ticker_strip(ticker_text, font)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Streaming cycle | headlines: {len(ur_list)}")
        run_cycle(base_rgb, ticker_strip, strip_w, strip_h, CYCLE_DURATION_SEC)

if __name__ == "__main__":
    main()
