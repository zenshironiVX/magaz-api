"""
MAGA Z — Discord Sender Backend
FastAPI + Deploy บน Render.com (ฟรี)
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import requests
import re
import time
import os
import json

app = FastAPI(title="MAGA Z Discord Sender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# ⚙️ CONFIG — ตั้งค่าใน Render Environment Variables
# ─────────────────────────────────────────
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER     = os.environ.get("GITHUB_USER", "zenshironiVX")
GITHUB_REPO_BASE = os.environ.get("GITHUB_REPO_BASE", "my-manga")

# URL ของ manga_meta.js บน GitHub Raw
# เช่น https://raw.githubusercontent.com/zenshironiVX/manga-meta/main/manga_meta.js
MANGA_META_URL  = os.environ.get(
    "MANGA_META_URL",
    f"https://raw.githubusercontent.com/{GITHUB_USER}/manga-meta/main/manga_meta.js"
)

GH_HEADERS = lambda: {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ─────────────────────────────────────────
# 🗂️ Cache Layer
# ─────────────────────────────────────────
_cache = {
    "meta": None, "meta_ts": 0,
    "tree": None, "tree_ts": 0,
}
CACHE_TTL = 600  # 10 นาที

# ─────────────────────────────────────────
# 🔧 Helpers
# ─────────────────────────────────────────
def sanitize(name: str) -> str:
    name = re.sub(r'\s+', ' ', str(name))
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()[:50]

def get_manga_meta() -> dict:
    if _cache["meta"] and time.time() - _cache["meta_ts"] < CACHE_TTL:
        return _cache["meta"]
    try:
        res = requests.get(MANGA_META_URL, timeout=15)
        res.raise_for_status()
        js = res.text
        json_str = re.sub(r'^(?:const|var|let)\s+\w+\s*=\s*', '', js).strip()
        if json_str.endswith(";"): json_str = json_str[:-1]
        data = json.loads(json_str)
        _cache["meta"] = data
        _cache["meta_ts"] = time.time()
        return data
    except Exception as e:
        raise HTTPException(500, f"โหลด manga_meta.js ไม่ได้: {e}")

def discover_repos() -> list[str]:
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{GITHUB_USER}/repos?per_page=100&page={page}"
        try:
            res = requests.get(url, headers=GH_HEADERS(), timeout=10)
            data = res.json()
            if not data or not isinstance(data, list): break
            for r in data:
                name = r.get("name", "")
                if re.match(rf"^{re.escape(GITHUB_REPO_BASE)}-\d+$", name):
                    repos.append(f"{GITHUB_USER}/{name}")
            if len(data) < 100: break
            page += 1
        except: break
    repos.sort(key=lambda r: int(r.rsplit("-", 1)[-1]))
    return repos

def get_github_tree() -> dict:
    if _cache["tree"] and time.time() - _cache["tree_ts"] < CACHE_TTL:
        return _cache["tree"]
    repos = discover_repos()
    existing = {}
    for full_repo in repos:
        repo_name = full_repo.split("/")[1]
        url = f"https://api.github.com/repos/{full_repo}/git/trees/main?recursive=1"
        try:
            res = requests.get(url, headers=GH_HEADERS(), timeout=15)
            if res.status_code == 200:
                for item in res.json().get("tree", []):
                    if item["path"].endswith(".html"):
                        page_url = f"https://{GITHUB_USER}.github.io/{repo_name}/{item['path']}"
                        existing[item["path"]] = page_url
        except: pass
    _cache["tree"] = existing
    _cache["tree_ts"] = time.time()
    return existing

# ─────────────────────────────────────────
# 📡 API Routes
# ─────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "MAGA Z API Online 🟢"}

@app.get("/api/cover")
def api_cover(url: str):
    """Proxy รูปปกเพื่อหลีกเลี่ยง hotlink protection รองรับทุก format"""
    if not url.startswith("http"):
        raise HTTPException(400, "URL ไม่ถูกต้อง")
    try:
        domain = url.split("/")[0] + "//" + url.split("/")[2] + "/"
        res = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": domain,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        })
        # กำหนด content type ตาม extension ถ้า header ไม่บอก
        content_type = res.headers.get("Content-Type", "")
        if not content_type or "text" in content_type:
            ext = url.split(".")[-1].lower().split("?")[0]
            type_map = {
                "avif": "image/avif",
                "webp": "image/webp",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
                "gif": "image/gif",
            }
            content_type = type_map.get(ext, "image/jpeg")
        return Response(
            content=res.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )
    except Exception as e:
        raise HTTPException(500, f"โหลดรูปไม่ได้: {e}")

@app.get("/api/manga")
def api_manga():
    """คืน manga_meta ทั้งหมด"""
    return get_manga_meta()

@app.get("/api/tree-stats")
def api_tree_stats():
    """สถิติจำนวนไฟล์ที่อัปแล้วบน GitHub Pages"""
    tree = get_github_tree()
    return {"total_files": len(tree), "cached": bool(_cache["tree"])}

@app.get("/api/refresh")
def api_refresh():
    """รีเฟรช cache ทั้งหมด"""
    _cache["meta"] = None
    _cache["meta_ts"] = 0
    _cache["tree"] = None
    _cache["tree_ts"] = 0
    tree = get_github_tree()
    meta = get_manga_meta()
    total_manga = sum(len(v) for v in meta.values())
    return {"files_on_github": len(tree), "total_manga": total_manga}

class SendRequest(BaseModel):
    webhook_url: str
    genre: str
    title: str
    cover_url: str = ""
    episodes: list[str] = []  # ว่าง = ส่งทุกตอน

@app.post("/api/send")
def api_send(req: SendRequest):
    """ส่งมังงะเข้า Discord webhook"""

    # ตรวจ webhook
    if "discord.com/api/webhooks" not in req.webhook_url:
        raise HTTPException(400, "Discord Webhook URL ไม่ถูกต้อง")

    # ดึงข้อมูล
    meta = get_manga_meta()
    manga_info = meta.get(req.genre, {}).get(req.title)
    if not manga_info:
        raise HTTPException(404, f"ไม่พบ: {req.title}")

    tree = get_github_tree()

    # สร้าง filename สำหรับแต่ละตอน
    safe_title = sanitize(req.title).replace(" ", "_").replace(".", "")
    all_eps = list(manga_info.get("episodes", {}).keys())
    
    # Natural sort
    def nat_key(s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]
    all_eps.sort(key=nat_key)

    target_eps = req.episodes if req.episodes else all_eps

    ep_links = []
    for ep in target_eps:
        safe_ep = sanitize(ep).replace(" ", "_").replace(".", "")
        filename = f"{safe_title}_{safe_ep}.html"
        url = tree.get(filename, "")
        if url:
            ep_links.append((ep, url))

    if not ep_links:
        raise HTTPException(404, "ยังไม่มีตอนที่อัปขึ้น GitHub Pages เลย")

    # แบ่ง chunk + ส่ง Discord
    chunks = []
    curr = ""
    for ep, link in ep_links:
        line = f"🔹 {ep}: [อ่านเลย]({link})\n"
        if len(curr) + len(line) > 3800:
            chunks.append(curr)
            curr = line
        else:
            curr += line
    if curr: chunks.append(curr)

    for i, chunk in enumerate(chunks):
        embed = {
            "title": f"📚 {req.title}" if i == 0 else f"📚 {req.title} (ต่อ {i+1})",
            "description": (
                f"จำนวนตอน: **{len(ep_links)} ตอน**\n\nรายการตอน:\n{chunk}"
                if i == 0 else f"รายการตอน:\n{chunk}"
            ),
            "color": 16738740,
            "footer": {"text": f"MAGA Z  •  by Zenshi  •  {i+1}/{len(chunks)}"}
        }
        if i == 0 and req.cover_url:
            embed["thumbnail"] = {"url": req.cover_url}
        try:
            requests.post(req.webhook_url, json={"embeds": [embed]}, timeout=10)
        except Exception as e:
            raise HTTPException(500, f"ส่ง Discord ไม่ได้: {e}")
        if i < len(chunks) - 1:
            time.sleep(2)

    return {
        "success": True,
        "sent_episodes": len(ep_links),
        "skipped": len(target_eps) - len(ep_links),
        "messages": len(chunks)
    }