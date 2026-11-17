#!/usr/bin/env python3
import json
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "posts.json"
OUT_DIR = ROOT / "dist"
TEMPLATE_DIR = ROOT / "assets"


def format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def render() -> None:
    posts = []
    if DATA_PATH.exists():
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        posts = payload.get("posts", [])
    posts = sorted(posts, key=lambda x: x.get("published_at", "1970-01-01T00:00:00+00:00"), reverse=True)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["format_date"] = format_date
    template = env.get_template("index.html")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(
        template.render(posts=posts, post_count=len(posts), site_title="倒霉鬼的倒霉日记"),
        encoding="utf-8",
    )
    guestbook_template = env.get_template("guestbook.html")
    (OUT_DIR / "guestbook.html").write_text(
        guestbook_template.render(site_title="倒霉鬼的倒霉日记"),
        encoding="utf-8",
    )
    (OUT_DIR / "styles.css").write_text((TEMPLATE_DIR / "styles.css").read_text(encoding="utf-8"), encoding="utf-8")
    (OUT_DIR / "app.js").write_text((TEMPLATE_DIR / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
    image_dir = ROOT / "data" / "images"
    if image_dir.exists():
        shutil.copytree(image_dir, OUT_DIR / "images", dirs_exist_ok=True)


if __name__ == "__main__":
    render()
