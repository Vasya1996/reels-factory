# -*- coding: utf-8 -*-
"""Контекстный подбор b-roll: Pexels + Pixabay + Coverr + локальная библиотека, ранжирование CLIP.

Отличие от подбора, который сейчас в проде (`editplan._pick_asset`): скор считается
не только по фразе, но и по КОНТЕКСТУ СЦЕНАРИЯ, плюс есть анти-контекст.

    score = 0.65*похожесть_на_фразу + 0.35*похожесть_на_домен
            - 0.70*max(0, похожесть_на_анти - похожесть_на_домен)   (+0.02 за вертикаль)

Зачем: на фразе «можно автоматизировать почти всё» сток без контекста выдаёт
промышленную робо-руку на заводе, хотя ролик про автоматизацию НА ЭКРАНЕ.
С анти-контекстом «industrial robotic arm, factory, humanoid robot» робот получает
штраф и уступает место кадру с интерфейсом.

Запуск:
    python broll_context_retrieval.py --windows windows.json --out picks.json

Формат windows.json:
{
  "context": {
    "domain_ru": "...", "domain_en": "...", "anti_en": "..."
  },
  "windows": [
    {"id": "S1a", "start": 8.30, "end": 10.42,
     "speech": "набор инструкций, который нейросеть запоминает",
     "ru": "список инструкций и правил, чек-лист на бумаге и на экране",
     "en": "checklist of instructions on notebook and screen close up",
     "q": ["writing checklist notebook", "notes list on screen"]}
  ]
}

Ключи API: переменные окружения PEXELS_API_KEY / PIXABAY_API_KEY / COVERR_API_KEY,
либо файлы в каталоге --keys-dir (по умолчанию ~/Desktop/стоковые):
«Pexels API key.txt», «pixabay api.txt», «coverr.txt».
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (reels-factory-broll)"          # без него WAF Pexels отдаёт 403
W_PHRASE, W_DOMAIN, W_ANTI, PORTRAIT_BONUS = 0.65, 0.35, 0.70, 0.02

STATS = {s: {"search": 0, "hits": 0, "kept": 0, "downloaded": 0,
             "skipped_landscape": 0, "empty": []} for s in ("pexels", "pixabay", "coverr")}


# --------------------------------------------------------------------------- ключи
def read_key(env_name: str, filename: str, keys_dir: Path) -> str:
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    p = keys_dir / filename
    if p.exists():
        return io.open(p, encoding="utf-8-sig").read().strip()
    return ""


# --------------------------------------------------------------------------- провайдеры
def pexels_search(query, key, per_page=4):
    """Единственный из трёх, кто умеет серверный фильтр вертикали (orientation=portrait)."""
    if not key:
        return []
    STATS["pexels"]["search"] += 1
    params = urllib.parse.urlencode({"query": query, "orientation": "portrait",
                                     "per_page": per_page, "size": "medium"})
    req = urllib.request.Request(f"https://api.pexels.com/videos/search?{params}",
                                 headers={"Authorization": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [pexels] ошибка '{query}': {e}")
        return []
    vids = data.get("videos", [])
    STATS["pexels"]["hits"] += len(vids)
    if not vids:
        STATS["pexels"]["empty"].append(query)
    out = []
    for v in vids:
        files = [f for f in v.get("video_files", []) if f.get("link")]
        portrait = [f for f in files if (f.get("height") or 0) > (f.get("width") or 0)]
        if not portrait:
            STATS["pexels"]["skipped_landscape"] += 1
            continue
        portrait.sort(key=lambda f: abs((f.get("height") or 0) - 1600))  # ближе к 1600px, не 4K
        out.append(dict(source="pexels", id=v["id"], url=portrait[0]["link"], query=query))
    STATS["pexels"]["kept"] += len(out)
    return out


def pixabay_search(query, key, per_page=4):
    """Ориентацию не фильтрует (проверено: orientation игнорируется, min_height не помогает,
    вертикали ~1 клип из 30) — режем сами по width/height ДО скачивания."""
    if not key:
        return []
    STATS["pixabay"]["search"] += 1
    params = urllib.parse.urlencode({"key": key, "q": query, "per_page": 30,
                                     "video_type": "film", "safesearch": "true"})
    req = urllib.request.Request(f"https://pixabay.com/api/videos/?{params}",
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [pixabay] ошибка '{query}': {e}")
        return []
    hits = data.get("hits", [])
    STATS["pixabay"]["hits"] += len(hits)
    out = []
    for h in hits:
        vs = h.get("videos", {})
        vert = [(k, v) for k, v in vs.items()
                if v.get("url") and (v.get("height") or 0) > (v.get("width") or 0)]
        if not vert:
            STATS["pixabay"]["skipped_landscape"] += 1
            continue
        vert.sort(key=lambda kv: abs((kv[1].get("height") or 0) - 1600))
        out.append(dict(source="pixabay", id=h["id"], url=vert[0][1]["url"], query=query))
        if len(out) >= per_page:
            break
    if not out:
        STATS["pixabay"]["empty"].append(query)
    STATS["pixabay"]["kept"] += len(out)
    return out


def coverr_search(query, key, per_page=4):
    """Авторизация Bearer. В выдаче есть флаг is_vertical. Библиотека маленькая:
    на 18 запросов вернулось 17 клипов и все горизонтальные — держать как третий источник."""
    if not key:
        return []
    STATS["coverr"]["search"] += 1
    params = urllib.parse.urlencode({"query": query, "page_size": 20, "urls": "true"})
    req = urllib.request.Request(f"https://api.coverr.co/videos?{params}",
                                 headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [coverr] ошибка '{query}': {e}")
        return []
    hits = data.get("hits", [])
    STATS["coverr"]["hits"] += len(hits)
    out = []
    for h in hits:
        if not h.get("is_vertical"):
            STATS["coverr"]["skipped_landscape"] += 1
            continue
        urls = h.get("urls") or {}
        link = urls.get("mp4_download") or urls.get("mp4") or urls.get("mp4_preview")
        if link:
            out.append(dict(source="coverr", id=h.get("id") or h.get("base_filename"),
                            url=link, query=query))
        if len(out) >= per_page:
            break
    if not out:
        STATS["coverr"]["empty"].append(query)
    STATS["coverr"]["kept"] += len(out)
    return out


def download(cand, dl_dir: Path):
    dst = dl_dir / f"{cand['source']}_{str(cand['id']).replace('/', '_')[:40]}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    for attempt in (1, 2):                       # ~2 из 20 загрузок Pexels отваливаются по таймауту
        try:
            req = urllib.request.Request(cand["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=150) as r, open(dst, "wb") as f:
                f.write(r.read())
            STATS[cand["source"]]["downloaded"] += 1
            return dst
        except Exception as e:
            print(f"    загрузка {dst.name}, попытка {attempt}: {e}")
    return None


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", required=True, help="json с context и windows")
    ap.add_argument("--out", default="picks.json")
    ap.add_argument("--dl-dir", default="broll_dl", help="куда складывать скачанные клипы")
    ap.add_argument("--engine-src", default=str(Path(__file__).resolve().parents[3] /
                                                "plugins/reels-factory/engine/src"),
                    help="путь к src движка (нужен reels_factory.broll_library)")
    ap.add_argument("--keys-dir", default=str(Path.home() / "Desktop" / "стоковые"))
    args = ap.parse_args()

    sys.path.insert(0, args.engine_src)
    from reels_factory import broll_library as lib      # CLIP: xlm-roberta-base-ViT-B-32

    keys_dir = Path(args.keys_dir)
    keys = dict(
        pexels=read_key("PEXELS_API_KEY", "Pexels API key.txt", keys_dir),
        pixabay=read_key("PIXABAY_API_KEY", "pixabay api.txt", keys_dir),
        coverr=read_key("COVERR_API_KEY", "coverr.txt", keys_dir),
    )
    print("ключи:", {k: ("есть" if v else "НЕТ") for k, v in keys.items()})

    spec = json.load(io.open(args.windows, encoding="utf-8"))
    ctx = spec["context"]
    dl_dir = Path(args.dl_dir)
    dl_dir.mkdir(parents=True, exist_ok=True)

    q_domain = lib.embed_text(ctx["domain_ru"])
    q_domain_en = lib.embed_text(ctx["domain_en"])
    q_anti = lib.embed_text(ctx["anti_en"])
    emb_cache = {}

    def clip_emb(path: Path):
        if path.name not in emb_cache:
            dur, res = lib.probe(path)
            with tempfile.TemporaryDirectory() as td:
                frames = lib.extract_frames(path, Path(td), n=4, duration=dur)
                emb = lib.embed_frames(frames) if frames else None
            emb_cache[path.name] = (emb, dur, res)
        return emb_cache[path.name]

    def score(emb, q_ru, q_en, portrait):
        phrase = max(lib.cosine(q_ru, emb), lib.cosine(q_en, emb))
        domain = max(lib.cosine(q_domain, emb), lib.cosine(q_domain_en, emb))
        anti = lib.cosine(q_anti, emb)
        total = W_PHRASE * phrase + W_DOMAIN * domain - W_ANTI * max(0.0, anti - domain)
        return round(total + (PORTRAIT_BONUS if portrait else 0), 4), \
            round(phrase, 4), round(domain, 4), round(anti, 4)

    results, used = {}, set()
    for w in spec["windows"]:
        need = w["end"] - w["start"]
        print(f"\n## {w['id']} [{w['start']}-{w['end']}] need {need:.2f}s | {w['speech']}")
        q_ru, q_en = lib.embed_text(w["ru"]), lib.embed_text(w["en"])
        cands = []
        for q in w["q"]:
            cands += pexels_search(q, keys["pexels"])
            cands += pixabay_search(q, keys["pixabay"])
            cands += coverr_search(q, keys["coverr"])
        paths = [(p, c["source"], c["query"]) for c in cands
                 for p in [download(c, dl_dir)] if p]
        for p in dl_dir.glob("*.mp4"):            # ранее скачанное тоже участвует
            if all(p != q[0] for q in paths):
                paths.append((p, "cached", "-"))

        rows = []
        for p, src, q in paths:
            emb, dur, res = clip_emb(p)
            if emb is None or dur < need * 1.15:  # клип должен быть длиннее окна с запасом
                continue
            portrait = bool(res and res[0] and res[1] > res[0])
            total, phrase, domain, anti = score(emb, q_ru, q_en, portrait)
            rows.append(dict(total=total, phrase=phrase, domain=domain, anti=anti,
                             name=p.name, path=str(p), src=src, query=q,
                             dur=round(dur, 1), res=res, portrait=portrait))
        rows.sort(key=lambda r: -r["total"])
        pick = next((r for r in rows if r["name"] not in used), None)   # дедуп по ролику
        if pick:
            used.add(pick["name"])
        results[w["id"]] = dict(window=w, pick=pick, top=rows[:6])
        for r in rows[:4]:
            mark = "<<<" if pick and r["name"] == pick["name"] else "   "
            print(f"  {mark} {r['total']:.4f} (фраза {r['phrase']:.3f} / домен {r['domain']:.3f}"
                  f" / анти {r['anti']:.3f}) {r['src']:7s} {r['name'][:34]}")

    json.dump({"results": results, "stats": STATS},
              io.open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n=== STATS ===")
    print(json.dumps(STATS, ensure_ascii=False, indent=1))
    print(f"\nзаписано: {args.out}")


if __name__ == "__main__":
    main()
