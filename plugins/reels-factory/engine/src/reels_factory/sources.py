"""Поиск и скачивание b-roll по ключевым словам фразы.

Два источника, выбор по наличию ключа:

  * **Pexels** (нужен PEXELS_API_KEY) — роялти-фри, коммерческая лицензия без
    атрибуции. Дефолт для проды: клипы можно публиковать клиентам без риска.
  * **YouTube через yt-dlp** (без ключа) — `ytsearch` ищет по словам и качает.
    Быстро и бесплатно, НО ролики под копирайтом: годится для теста и черновой
    сборки, для публикации клиентам — риск Content ID. Фолбэк, не дефолт.

Ключ читается из env (PEXELS_API_KEY) или файла .env в корне проекта — в код
ключ не пишется никогда. http/downloader — DI для тестов.

На вход — поисковый запрос (его даёт LLM из фразы сценария: «утром пью кофе» ->
«coffee morning pour»). На выход — путь к скачанному вертикальному клипу.
"""
import os
from pathlib import Path

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"

# Целимся в вертикаль под рилс; берём самый крупный файл не выше 1080 по ширине.
MAX_WIDTH = 1080


class SourceError(RuntimeError):
    pass


def load_pexels_key() -> str | None:
    """Ключ из env, иначе из .env в корне проекта. None — если нигде нет."""
    key = os.environ.get("PEXELS_API_KEY")
    if key:
        return key.strip()
    # .env лежит в корне репозитория плагина (на 4 уровня выше этого файла)
    for base in Path(__file__).resolve().parents:
        env = base / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("PEXELS_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


def search_pexels(query: str, *, per_page: int = 5, orientation: str = "portrait",
                  http=None, api_key: str | None = None) -> list:
    """Найти вертикальные клипы на Pexels. Возвращает список кандидатов:
    [{"id","duration","url"}] — url это прямая ссылка на mp4-файл нужного размера.
    """
    api_key = api_key or load_pexels_key()
    if not api_key:
        raise SourceError("нет PEXELS_API_KEY (env или .env) — используй search_youtube")
    if http is None:
        import requests
        http = requests

    resp = http.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "per_page": per_page, "orientation": orientation},
        headers={"Authorization": api_key}, timeout=30,
    )
    resp.raise_for_status()
    out = []
    for v in resp.json().get("videos", []):
        best = _best_file(v.get("video_files", []))
        if best:
            out.append({"id": v["id"], "duration": v.get("duration", 0), "url": best})
    return out


def _best_file(files: list) -> str | None:
    """Самый крупный mp4 не шире MAX_WIDTH (крупнее уже избыточно для рилса)."""
    ok = [f for f in files if f.get("file_type") == "video/mp4"
          and (f.get("width") or 0) <= MAX_WIDTH]
    pool = ok or [f for f in files if f.get("file_type") == "video/mp4"]
    if not pool:
        return None
    return max(pool, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0)).get("link")


def download(url: str, out_path, *, http=None) -> Path:
    """Скачать прямую ссылку на mp4 (Pexels-файл) в out_path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if http is None:
        import requests
        http = requests
    resp = http.get(url, timeout=120)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def search_youtube(query: str, out_path, *, n: int = 1, ydl=None) -> Path:
    """Фолбэк без ключа: ytsearch по словам, скачать первый результат.

    Копирайтные ролики — только для теста/черновика, не для публикации.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noplaylist": True,
    }
    if ydl is None:
        import yt_dlp
        ydl = yt_dlp.YoutubeDL(opts)
    with ydl:
        ydl.extract_info(f"ytsearch{n}:{query}", download=True)
    cands = sorted(out_path.parent.glob(out_path.stem + ".*"),
                   key=lambda p: p.stat().st_size, reverse=True)
    cands = [c for c in cands if c.suffix.lower() in (".mp4", ".mkv", ".webm")]
    if not cands:
        raise SourceError(f"ytsearch не дал файла по запросу {query!r}")
    return cands[0]


def fetch_broll(query: str, out_path, *, prefer: str = "pexels",
                http=None) -> dict:
    """Найти и скачать один b-roll по запросу. Возвращает
    {"path","source","query","credit"?}. Сначала Pexels (если есть ключ и
    результаты), иначе — YouTube.
    """
    out_path = Path(out_path)
    if prefer == "pexels" and load_pexels_key():
        try:
            hits = search_pexels(query, http=http)
            if hits:
                path = download(hits[0]["url"], out_path.with_suffix(".mp4"), http=http)
                return {"path": str(path), "source": "pexels", "query": query,
                        "credit": f"Pexels video {hits[0]['id']}"}
        except Exception:
            pass  # падаем на ютуб-фолбэк ниже, а не роняем весь ролик
    path = search_youtube(query, out_path)
    return {"path": str(path), "source": "youtube", "query": query}
