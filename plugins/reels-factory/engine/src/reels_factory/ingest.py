"""Приём видеоряда (broll): ссылка YouTube/др. (yt-dlp) или локальный файл."""
import json
from pathlib import Path


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def ingest(source: str, workdir) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if _is_url(source):
        import yt_dlp
        opts = {
            "outtmpl": str(workdir / "source.%(ext)s"),
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4",
            "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source, download=True)
        video = workdir / "source.mp4"
        if not video.exists():  # yt-dlp мог оставить другой контейнер
            cands = sorted(workdir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
            if not cands:
                raise RuntimeError("yt-dlp не оставил файла source.*")
            video = cands[0]
        meta = {"source_url_or_path": source, "video_path": str(video.resolve()),
                "title": info.get("title") or "", "duration_s": float(info.get("duration") or 0),
                "kind": "url"}
    else:
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(source)
        meta = {"source_url_or_path": source, "video_path": str(p.resolve()),
                "title": p.stem, "duration_s": 0.0, "kind": "local"}
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta
