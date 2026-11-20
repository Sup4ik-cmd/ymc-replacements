#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add a replacement track to ymc-replacements.

Adapted from Hazzz895/FckCensorData::append_track.py for our own repo:
writes manifest.json instead of list.json, uses our raw URL, no access to
FckCensor's Supabase/service_role key. Commits and pushes automatically.

Usage:
    python append_track.py                 # interactive
    python append_track.py 145054524       # pre-fill the id
    python append_track.py --dry-run ...   # show the entry, change nothing
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"
TRACKS = ROOT / "tracks"
CACHE = ROOT / "ym_cache.json"
DRY = "--dry-run" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--dry-run"]


def load_env():
    """Minimal .env reader (no dependency on python-dotenv)."""
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update(os.environ)
    return env


def say(prompt):
    return input(prompt).strip()


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if "tracks" not in data or not isinstance(data["tracks"], list):
        data["tracks"] = []
    return data


def info_from_yandex(track_id, token):
    """Return {title, artists, cover} or None. Never crashes the script."""
    try:
        from yandex_music import Client
    except ImportError:
        return None
    try:
        client = Client(token).init() if token else Client().init()
        track = client.tracks([str(track_id)])[0]
    except Exception as e:
        print("yandex metadata error:", e)
        return None
    artists = []
    for a in (track.artists or []):
        artists.append({"name": a.name, "id": str(a.id)})
    cover = getattr(track, "cover_uri", None)
    if cover:
        cover = re.sub(r"/[^/]+$", "/%%", cover)
    return {"title": track.title, "artists": artists, "cover": cover}


def cached_info(track_id, token):
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    if str(track_id) in cache:
        return cache[str(track_id)]
    got = info_from_yandex(track_id, token)
    if got:
        cache[str(track_id)] = got
        if not DRY:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return got


def put_file(track_id, url):
    """Copy a local file or download via yt-dlp.

    Returns (file_exists, thumbnail_url). The thumbnail is taken from the
    SoundCloud/yt-dlp metadata so it can be written into manifest.json.
    """
    TRACKS.mkdir(exist_ok=True)
    target = TRACKS / str(track_id)
    if not url:
        return target.exists(), None
    if not url.startswith("http"):
        src = Path(url).expanduser()
        if not src.exists():
            print("file not found:", src)
            return False, None
        if DRY:
            print("[dry-run] copy", src, "->", target)
            return True, None
        shutil.copy2(src, target)
        print("copied to", target)
        return True, None
    try:
        import yt_dlp
    except ImportError:
        print("yt-dlp is not installed; cannot download. pip install yt-dlp")
        return False, None
    answer = "y" if "soundcloud.com" in url else say("Download from url? (y/n) ").lower()
    if answer not in ("y", "yes", "д", "да"):
        return target.exists(), None
    opts = {"format": "bestaudio/best", "outtmpl": str(TRACKS / (str(track_id) + ".%(ext)s")),
            "quiet": False}
    if DRY:
        print("[dry-run] yt-dlp", url)
        return True, None
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    made = sorted(TRACKS.glob(str(track_id) + ".*"), key=lambda p: p.stat().st_mtime)
    if made:
        made[-1].replace(target)
        print("saved as", target)
    thumb = info.get("thumbnail") if isinstance(info, dict) else None
    if thumb:
        print("cover from source:", thumb)
    return target.exists(), thumb


def git(*args):
    if DRY:
        print("[dry-run] git", " ".join(args))
        return
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, timeout=180)
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    print(out.strip())
    if r.returncode != 0:
        print("git command failed:", args[0])


def main():
    env = load_env()
    token = env.get("API_TOKEN")
    manifest = load_manifest()
    existing = {str(t.get("id")) for t in manifest["tracks"] if t.get("id")}

    user = ARGS[0] if ARGS else say("Yandex Music track ID or URL: ")
    track_id = user.split("/")[-1].split("?")[0].strip()
    if not track_id.isdigit():
        print("bad track id:", track_id)
        return
    if track_id in existing and not DRY:
        print("track already in manifest:", track_id)
        return

    got = cached_info(track_id, token)
    if got:
        title = got.get("title") or ""
        artists = got.get("artists") or []
        cover = got.get("cover")
        print("Track name:", title, "-", ", ".join(a["name"] for a in artists))
    else:
        print("Track info not found; enter metadata manually.")
        title = say("Title: ")
        artists = []
        name = say("Artist name (Enter to skip): ")
        aid = say("Artist id (Enter to skip): ") if name else ""
        if name:
            artists = [{"name": name, "id": aid}]
        cover = say("Cover path (Enter to skip): ") or None

    url = say("Track URL or local file path (Enter to keep existing file): ")
    has_file, thumb = put_file(track_id, url)
    if not cover and thumb:
        cover = thumb
    repair = False
    if has_file:
        repair = say("Need the trex/sidx repair? (y/N) ").lower() in ("y", "yes", "д", "да")

    entry = {"id": track_id}
    if title:
        entry["title"] = title
    if cover:
        entry["cover"] = cover
    if artists and artists[0].get("name"):
        entry["artist"] = artists[0]["name"]
        if artists[0].get("id"):
            entry["artist_id"] = artists[0]["id"]
    if has_file:
        entry["file"] = track_id
    if repair:
        entry["repair"] = True
    print("entry:", json.dumps(entry, ensure_ascii=False))

    if DRY:
        return
    manifest["tracks"].append(entry)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    git("add", "manifest.json")
    if has_file:
        git("add", "tracks/" + track_id)
    git("commit", "-m", "add track «%s»" % (title or track_id))
    git("push", "origin", "main")
    print("done")


if __name__ == "__main__":
    main()
