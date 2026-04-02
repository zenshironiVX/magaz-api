"""
MAGA Z — Discord Sender Backend (JSON Chunked Version - หั่นไฟล์)
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel
import requests
import re
import os
import json
import gzip
import time
from urllib.parse import quote

app = FastAPI(title="MAGA Z Discord Sender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("กำลังโหลดไฟล์สารบัญ...")
global_error = None
try:
    with open(os.path.join(BASE_DIR, "manga_meta.json"), "r", encoding="utf-8") as f:
        META_DATA = json.load(f)
    with open(os.path.join(BASE_DIR, "manga_index.json"), "r", encoding="utf-8") as f:
        INDEX_DATA = json.load(f)
    print(f"✅ โหลดสารบัญสำเร็จ! พบ {len(META_DATA)} หมวดหมู่")
except Exception as e:
    print(f"❌ โหลดสารบัญล้มเหลว: {e}")
    global_error = str(e)
    META_DATA = {}
    INDEX_DATA = {}

@app.get("/")
def root():
    return {
        "status": "MAGA Z API Online 🟢 (Multi-files Version)",
        "loaded_genres": len(META_DATA),
        "error": global_error,
        "base_dir": BASE_DIR,
        "files_in_dir": os.listdir(BASE_DIR) if not global_error else []
    }

import io
try:
    from PIL import Image
    import pillow_heif
    if hasattr(pillow_heif, "register_avif_opener"):
        pillow_heif.register_avif_opener()
    elif hasattr(pillow_heif, "register_heif_opener"):
        pillow_heif.register_heif_opener()
    PILLOW_AVAILABLE = True
except Exception:
    PILLOW_AVAILABLE = False

try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
except ImportError:
    scraper = requests # fallback

@app.get("/api/cover")
def api_cover(url: str, discord: int = 0):
    if not url.startswith("http"): raise HTTPException(400, "URL ไม่ถูกต้อง")
    try:
        domain = url.split("/")[0] + "//" + url.split("/")[2] + "/"
        res = scraper.get(url, timeout=15, headers={"Referer": domain})
        content_type = res.headers.get("Content-Type", "")
        
        ext = url.split(".")[-1].lower().split("?")[0]
        if not content_type or not content_type.startswith("image/"):
            type_map = {"avif": "image/avif", "webp": "image/webp", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "bmp": "image/bmp"}
            content_type = type_map.get(ext, "image/jpeg")

        content_bytes = res.content
        
        # ถ้ารูปเป็น AVIF ให้แปลงร่างเป็น JPEG สดๆ เฉพาะตอนส่งให้ Discord (discord=1) เท่านั้น เพราะบนเว็บเบราว์เซอร์รองรับ AVIF อยู่แล้ว
        if discord == 1 and (ext == "avif" or "avif" in content_type) and PILLOW_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(content_bytes))
                out_io = io.BytesIO()
                img.convert("RGB").save(out_io, format="JPEG")
                content_bytes = out_io.getvalue()
                content_type = "image/jpeg"
            except Exception as cvt_err:
                print(f"แปลงไฟล์ AVIF ไม่สำเร็จ: {cvt_err}")

        return Response(content=content_bytes, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        raise HTTPException(500, f"โหลดรูปไม่ได้: {e}")

@app.get("/api/manga")
def api_manga():
    return META_DATA

# ฟังก์ชันวิ่งไปดึงข้อมูลจากไฟล์ย่อย (Part) ชั่วคราว
def get_episodes_data(genre, title):
    part_file = INDEX_DATA.get(genre, {}).get(title)
    if not part_file:
        return None
    full_path = os.path.join(BASE_DIR, part_file)
    if not os.path.exists(full_path):
        return None
    try:
        with gzip.open(full_path, "rt", encoding="utf-8") as f:
            part_data = json.load(f)
        return part_data.get(genre, {}).get(title, {}).get("episodes", {})
    except:
        return None

@app.get("/read", response_class=HTMLResponse)
def read_manga(genre: str, title: str, ep: str):
    episodes = get_episodes_data(genre, title)
    if not episodes or ep not in episodes:
        return "<h1 style='color:white; text-align:center;'>❌ ไม่พบตอนที่ระบุ</h1>"

    images = episodes[ep]
    if not isinstance(images, list): images = []
    img_tags = "".join([f'<img src="/api/cover?url={quote(img)}" loading="lazy">' for img in images])

    return f"""
    <!DOCTYPE html>
    <html lang="th">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title} - {ep}</title>
    <style>body {{ background: #050508; color: #fff; text-align: center; font-family: sans-serif; margin: 0; padding: 0; }} .container {{ max-width: 800px; margin: 0 auto; padding: 20px 10px; }} h2 {{ color: #ff8fab; margin-bottom: 5px; }} p {{ color: #888; margin-bottom: 25px; }} img {{ width: 100%; display: block; margin: 0 auto; }}</style>
    </head><body><div class="container"><h2>{title}</h2><p>{ep}</p>{img_tags}</div></body></html>
    """

class SendRequest(BaseModel):
    webhook_url: str
    genre: str
    title: str
    cover_url: str = ""
    episodes: list[str] = []

@app.post("/api/send")
def api_send(req: SendRequest, request: Request):
    if "discord.com/api/webhooks" not in req.webhook_url:
        raise HTTPException(400, "Discord Webhook URL ไม่ถูกต้อง")

    if req.genre not in INDEX_DATA or req.title not in INDEX_DATA[req.genre]:
        raise HTTPException(404, f"ไม่พบมังงะเรื่อง: {req.title}")

    all_eps = list(META_DATA.get(req.genre, {}).get(req.title, {}).get("episodes", {}).keys())
    def nat_key(s): return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]
    all_eps.sort(key=nat_key)

    target_eps = req.episodes if req.episodes else all_eps
    base_url = str(request.base_url).rstrip("/")
    
    ep_links = []
    for ep in target_eps:
        if ep in all_eps:
            link = f"{base_url}/read?genre={quote(req.genre)}&title={quote(req.title)}&ep={quote(ep)}"
            ep_links.append((ep, link))

    if not ep_links: raise HTTPException(404, "ไม่มีตอนที่เลือกอยู่ในระบบฐานข้อมูล")

    chunks = []
    curr = ""
    for ep, link in ep_links:
        line = f"🔹 {ep}: [อ่านเลย]({link})\n"
        if len(curr) + len(line) > 3800:
            chunks.append(curr); curr = line
        else:
            curr += line
    if curr: chunks.append(curr)

    for i, chunk in enumerate(chunks):
        embed = {
            "title": f"📚 {req.title}" if i == 0 else f"📚 {req.title} (ต่อ {i+1})",
            "description": f"จำนวนตอน: **{len(ep_links)} ตอน**\n\nรายการตอน:\n{chunk}" if i == 0 else f"รายการตอน:\n{chunk}",
            "color": 16738740,
            "footer": {"text": f"MAGA Z  •  by Zenshi  •  {i+1}/{len(chunks)}"}
        }
        if i == 0 and req.cover_url:
            proxied_url = f"{base_url}/api/cover?url={quote(req.cover_url)}&discord=1"
            embed["thumbnail"] = {"url": proxied_url}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.post(req.webhook_url, json={"embeds": [embed]}, timeout=10)
                if res.status_code == 429:
                    # ติด Rate Limit หรือโดน Cloudflare แบนชั่วคราว
                    wait_time = 5 * (attempt + 1)
                    print(f"⚠️ ติด Rate limit 429 ขอลองใหม่ใน {wait_time} วิ...")
                    time.sleep(wait_time)
                    continue
                if not res.ok: 
                    raise Exception(f"Discord ปฏิเสธการรับข้อมูล ({res.status_code}): {res.text}")
                break # ส่งผ่านแล้ว ออกจากลูป retry
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise HTTPException(500, f"ส่ง Discord ไม่ได้ (เครือข่ายมีปัญหา): {str(e)}")
                time.sleep(5)
            except Exception as e:
                # ถ้าเจอ error ปกติให้ปล่อยไปถ้าถึงรอบสุดท้าย
                if attempt == max_retries - 1:
                    raise HTTPException(500, f"ส่ง Discord ไม่ได้: {str(e)}")
                time.sleep(5)
                
        if i < len(chunks) - 1:
            # ใช้ Sleep 2.5 วิ ระหว่างหน้ากันโดน Cloudflare แบนเพิ่มถ้าส่งเยอะๆ
            time.sleep(2.5)

    return {"success": True, "sent_episodes": len(ep_links), "skipped": len(target_eps) - len(ep_links), "messages": len(chunks)}