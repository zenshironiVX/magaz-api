"""
MAGA Z — Discord Sender Backend (Local JSON Version)
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

# ─────────────────────────────────────────
# 🗂️ โหลดข้อมูล JSON (รองรับไฟล์บีบอัด .gz เพื่อหลบข้อจำกัด GitHub)
# ─────────────────────────────────────────
print("กำลังโหลดฐานข้อมูลมังงะ...")
MANGA_DATA = {}
try:
    if os.path.exists("manga_data.json.gz"):
        with gzip.open("manga_data.json.gz", "rt", encoding="utf-8") as f:
            MANGA_DATA = json.load(f)
    elif os.path.exists("manga_data.json"):
        with open("manga_data.json", "r", encoding="utf-8") as f:
            MANGA_DATA = json.load(f)
    else:
        print("❌ ข้อผิดพลาด: ไม่พบไฟล์ manga_data.json หรือ manga_data.json.gz")
        
    print(f"✅ โหลดข้อมูลสำเร็จแล้ว ({len(MANGA_DATA)} หมวดหมู่)")
except Exception as e:
    print(f"❌ โหลดข้อมูลล้มเหลว: {e}")

# ส่งรายชื่อมังงะให้หน้าเว็บ (โดยไม่ส่งรูปไปให้หนักเครื่อง)
def get_manga_meta():
    meta = {}
    for genre, mangas in MANGA_DATA.items():
        meta[genre] = {}
        for title, info in mangas.items():
            meta[genre][title] = {
                "cover": info.get("cover", ""),
                "episodes": {ep: {} for ep in info.get("episodes", {}).keys()}
            }
    return meta

# ─────────────────────────────────────────
# 📡 API Routes
# ─────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "MAGA Z API Online 🟢", "loaded_genres": len(MANGA_DATA)}

@app.get("/api/cover")
def api_cover(url: str):
    """Proxy รูปเพื่อหลีกเลี่ยง hotlink protection และแก้ปัญหา .avif ไม่ขึ้น"""
    if not url.startswith("http"):
        raise HTTPException(400, "URL ไม่ถูกต้อง")
    try:
        domain = url.split("/")[0] + "//" + url.split("/")[2] + "/"
        res = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": domain,
        })
        
        # บังคับประเภทไฟล์ให้ถูกต้อง
        content_type = res.headers.get("Content-Type", "")
        if not content_type or not content_type.startswith("image/"):
            ext = url.split(".")[-1].lower().split("?")[0]
            type_map = {"avif": "image/avif", "webp": "image/webp", "jpg": "image/jpeg", "png": "image/png"}
            content_type = type_map.get(ext, "image/jpeg")
            
        return Response(content=res.content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        raise HTTPException(500, f"โหลดรูปไม่ได้: {e}")

@app.get("/api/manga")
def api_manga():
    """ส่งข้อมูลรายการมังงะและตอนให้ Frontend (index.html)"""
    return get_manga_meta()

@app.get("/read", response_class=HTMLResponse)
def read_manga(genre: str, title: str, ep: str):
    """ระบบสร้างหน้าอ่านมังงะแบบสดๆ ดึงรูปลงมาให้ทันทีเมื่อคนกดลิงก์ใน Discord"""
    episodes = MANGA_DATA.get(genre, {}).get(title, {}).get("episodes", {})
    if ep not in episodes:
        return "<h1 style='color:white; text-align:center; padding:50px;'>❌ ไม่พบข้อมูลตอนที่ระบุ</h1>"

    images = episodes[ep]
    if not isinstance(images, list): images = []

    # แปลงลิงก์รูปให้ผ่านตัว Proxy เพื่อป้องกันเว็บต้นทางบล็อค
    img_tags = "".join([f'<img src="/api/cover?url={quote(img)}" loading="lazy">' for img in images])

    return f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - {ep}</title>
        <style>
            body {{ background: #050508; color: #fff; text-align: center; font-family: sans-serif; margin: 0; padding: 0; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px 10px; }}
            h2 {{ color: #ff8fab; margin-bottom: 5px; }}
            p {{ color: #888; margin-bottom: 25px; }}
            img {{ width: 100%; display: block; margin: 0 auto; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>{title}</h2>
            <p>{ep}</p>
            {img_tags}
        </div>
    </body>
    </html>
    """

class SendRequest(BaseModel):
    webhook_url: str
    genre: str
    title: str
    cover_url: str = ""
    episodes: list[str] = []

@app.post("/api/send")
def api_send(req: SendRequest, request: Request):
    """ส่งข้อความเข้า Discord Webhook + แนบลิงก์หน้า /read"""
    if "discord.com/api/webhooks" not in req.webhook_url:
        raise HTTPException(400, "Discord Webhook URL ไม่ถูกต้อง")

    manga_info = MANGA_DATA.get(req.genre, {}).get(req.title)
    if not manga_info:
        raise HTTPException(404, f"ไม่พบมังงะเรื่อง: {req.title}")

    # ดึงรายชื่อตอนและเรียงลำดับให้ถูกต้อง
    all_eps = list(manga_info.get("episodes", {}).keys())
    def nat_key(s): return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]
    all_eps.sort(key=nat_key)

    target_eps = req.episodes if req.episodes else all_eps
    base_url = str(request.base_url).rstrip("/")
    
    ep_links = []
    for ep in target_eps:
        if ep in all_eps:
            # สร้างลิงก์ที่ชี้มาที่หน้าอ่านมังงะ (ระบบเราเอง)
            link = f"{base_url}/read?genre={quote(req.genre)}&title={quote(req.title)}&ep={quote(ep)}"
            ep_links.append((ep, link))

    if not ep_links:
        raise HTTPException(404, "ไม่มีตอนที่เลือกอยู่ในระบบฐานข้อมูล")

    # แบ่งส่งทีละก้อนกัน Discord บล็อกเพราะข้อความยาวเกิน
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
        
        # ป้องกัน Discord Error เวลาเจอรูป .avif
        if i == 0 and req.cover_url and not req.cover_url.lower().endswith(".avif"):
            embed["thumbnail"] = {"url": req.cover_url}
        
        try:
            res = requests.post(req.webhook_url, json={"embeds": [embed]}, timeout=10)
            # เช็คว่า Discord ตอบรับคำขอส่งสำเร็จหรือไม่
            if not res.ok: raise Exception(f"Discord ปฏิเสธการรับข้อมูล ({res.status_code}): {res.text}")
        except Exception as e:
            raise HTTPException(500, f"ส่ง Discord ไม่ได้: {str(e)}")
            
        if i < len(chunks) - 1: time.sleep(2)

    return {"success": True, "sent_episodes": len(ep_links), "skipped": len(target_eps) - len(ep_links), "messages": len(chunks)}