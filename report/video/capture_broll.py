"""Video B-roll of the live site (D-0013 W3-2): scripted 1080p captures for Samuel to narrate over.

Each clip is recorded by Playwright (Chromium, 1920×1080, WebM) in its own browser context, then converted with
OpenCV: `VideoCapture` → MP4 (`VideoWriter`, mp4v) and a 640-px GIF (`cv2.imwriteanimation`, 6 fps).
Clips whose page does not exist yet (e.g. /health, flood replay before W1 ships them) are skipped and listed.

Outputs (videos are large and gitignored; the manifest is committed):
  results/video_assets/<clip>.{webm,mp4,gif}
  results/video_assets/manifest.json   url, seconds, sizes, sha256, captured_utc, what the clip shows

    python report/video/capture_broll.py [--base https://d2aes2r6og8aap.cloudfront.net] [--only judge home]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "video_assets"
BASE = "https://d2aes2r6og8aap.cloudfront.net"
W, H = 1920, 1080


def smooth_scroll(page, seconds: float, steps_per_s: int = 30) -> None:
    total = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
    n = max(int(seconds * steps_per_s), 1)
    for i in range(1, n + 1):
        page.evaluate(f"window.scrollTo(0, {total * i / n})")
        time.sleep(1 / steps_per_s)


def sweep_slider(page, selector: str, seconds: float, steps: int = 90) -> None:
    lo, hi = page.eval_on_selector(selector, "e => [parseFloat(e.min), parseFloat(e.max)]")
    vals = list(np.linspace(lo, hi, steps)) + list(np.linspace(hi, lo, steps // 2))
    for v in vals:
        page.eval_on_selector(selector, "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }", v)
        time.sleep(seconds / len(vals))


def clip_home(page):
    page.goto(f"{BASE}/index.html", wait_until="networkidle")
    time.sleep(3)
    smooth_scroll(page, 10)
    time.sleep(2)


def clip_salt_creek_slider(page):
    page.goto(f"{BASE}/site.html?cam=IL_Salt_Creek_at_Wood_Dale", wait_until="networkidle")
    page.wait_for_selector("#stage")
    time.sleep(3)
    # put the "What's under water" panel (frame + slider) at the top of the viewport, frame fully visible
    page.evaluate("""() => {
        const h = [...document.querySelectorAll('h1,h2,h3')].find(e => /under water/i.test(e.textContent));
        if (h) window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 70);
    }""")
    time.sleep(1)
    sweep_slider(page, "#stage", 9)
    time.sleep(2)


def clip_judge(page):
    page.goto(f"{BASE}/judge.html", wait_until="networkidle")
    time.sleep(3)
    smooth_scroll(page, 25)
    time.sleep(2)


def clip_replay(page):
    page.goto(f"{BASE}/site.html?cam=IL_Salt_Creek_at_Wood_Dale", wait_until="networkidle")
    page.wait_for_selector("#rp-play", state="visible", timeout=30000)
    page.evaluate("() => { const e = document.getElementById('replay-sec'); window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 70); }")
    time.sleep(2)
    page.click("#rp-play")
    time.sleep(28)


def clip_simple(path: str, scroll_s: float = 8):
    def f(page):
        page.goto(f"{BASE}/{path}", wait_until="networkidle")
        time.sleep(3)
        smooth_scroll(page, scroll_s)
        time.sleep(2)
    return f


CLIPS = {
    "home": (clip_home, "index.html", "Home: fleet map, status pills, headline strip, featured cameras"),
    "salt_creek_slider": (clip_salt_creek_slider, "site.html?cam=IL_Salt_Creek_at_Wood_Dale",
                          "Salt Creek site page: stage slider swept low→high→low, connected wet overlay filling the channel"),
    "judge": (clip_judge, "judge.html", "/judge: frozen-test numbers, agent eval, COOL, failure cases, reproduce"),
    "approvals": (clip_simple("approvals.html"), "approvals.html", "/approvals: pending and decided human approvals"),
    "proof": (clip_simple("proof.html"), "proof.html", "/proof: COOL build provenance, instance identity, AMI"),
    "health": (clip_simple("health.html", 12), "health.html", "/health: fleet camera-health report (W2/W1): offline, view changed, IR stuck on, poor visibility; ticket drafts needing approval"),
    "replay_salt_creek": (clip_replay, "site.html?cam=IL_Salt_Creek_at_Wood_Dale",
                          "Flood replay, Salt Creek 3 Jul 2026 (out of sample): overlay rising frame by frame, chart cursor, agent log and drafted alert in time"),
    "api": (clip_simple("api.html", 6), "api.html", "/api.html: public JSON feed and Atom feed documentation"),
}


def exists(path: str) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/{path.split('?')[0]}", method="HEAD"), timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def convert(webm: Path, name: str) -> dict:
    cap = cv2.VideoCapture(str(webm))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = []
    mp4 = OUT / f"{name}.mp4"
    vw = None
    i = 0
    gif_every = max(int(round(fps / 6)), 1)
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if vw is None:
            vw = cv2.VideoWriter(str(mp4), cv2.VideoWriter_fourcc(*"mp4v"), fps, (fr.shape[1], fr.shape[0]))
        vw.write(fr)
        if i % gif_every == 0:
            frames.append(cv2.resize(fr, (640, int(fr.shape[0] * 640 / fr.shape[1])), interpolation=cv2.INTER_AREA))
        i += 1
    cap.release()
    if vw is not None:
        vw.release()
    gif = OUT / f"{name}.gif"
    if frames:
        anim = cv2.Animation()
        anim.frames = frames
        anim.durations = [int(1000 * gif_every / fps)] * len(frames)
        cv2.imwriteanimation(str(gif), anim)
    return {"frames": i, "fps": round(fps, 2), "seconds": round(i / fps, 1)}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def main() -> None:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_raw"
    shutil.rmtree(tmp, ignore_errors=True)
    mpath = OUT / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"clips": {}}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, (fn, path, what) in CLIPS.items():
            if args.only and name not in args.only:
                continue
            if not exists(path):
                manifest["clips"][name] = {"url": f"{BASE}/{path}", "what": what, "status": "skipped: page not live yet"}
                print(f"{name}: skipped ({path} not live)")
                continue
            ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                      record_video_size={"width": W, "height": H}, color_scheme="light")
            page = ctx.new_page()
            fn(page)
            vid = Path(page.video.path())
            ctx.close()
            webm = OUT / f"{name}.webm"
            shutil.move(str(vid), webm)
            info = convert(webm, name)
            manifest["clips"][name] = {
                "url": f"{BASE}/{path}", "what": what, "status": "captured", **info,
                "captured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": {ext: {"bytes": (OUT / f"{name}.{ext}").stat().st_size, "sha256": sha(OUT / f"{name}.{ext}")}
                          for ext in ("webm", "mp4", "gif") if (OUT / f"{name}.{ext}").exists()}}
            print(f"{name}: {info['seconds']} s")
        browser.close()
    shutil.rmtree(tmp, ignore_errors=True)
    manifest["viewport"] = f"{W}x{H}"
    manifest["note"] = "Videos are gitignored (size); regenerate with this script. Frames on the site are face-blurred upstream (YuNet)."
    mpath.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"manifest: {mpath}")


if __name__ == "__main__":
    main()
