"""Распознавание речи с пословными таймкодами через faster-whisper.

Вход:  видео или аудио файл (голос блогерши).
Выход: <workdir>/words.json  — [{id,start,end,text,prob}], отсортировано по времени.
       <workdir>/audio16k.wav — извлечённое аудио 16 кГц моно.

Устройство выбирается автоматически: пробуем CUDA, при ошибке cuDNN/драйвера
откатываемся на CPU.
"""
import os, sys, json, subprocess
from pathlib import Path
from reels_factory.config import FFMPEG
from reels_factory.glossary import fix_text


def _add_nvidia_dlls():
    """Добавить в поиск DLL папки cuDNN/cuBLAS из pip-пакетов nvidia-* (нужно ctranslate2 на Windows)."""
    try:
        import nvidia
        base = list(nvidia.__path__)[0]
        for sub in ("cudnn", "cublas"):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def extract_audio(src, wav):
    subprocess.run(
        [FFMPEG, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
        check=True, capture_output=True,
    )


def transcribe(wav, model_size, language, device):
    from faster_whisper import WhisperModel

    tried = []
    order = []
    if device in ("auto", "cuda"):
        order.append(("cuda", "int8"))
    if device in ("auto", "cpu"):
        order.append(("cpu", "int8"))
    if device == "cpu":
        order = [("cpu", "int8")]

    for dev, ct in order:
        try:
            sys.stderr.write(f"[transcribe] loading model={model_size} device={dev} compute={ct}\n")
            model = WhisperModel(model_size, device=dev, compute_type=ct, cpu_threads=os.cpu_count() or 4)
            segments, info = model.transcribe(
                wav,
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
                beam_size=5,
            )
            words = []
            wid = 0
            for seg in segments:
                if seg.words:
                    for w in seg.words:
                        t = w.word.strip()
                        if not t:
                            continue
                        words.append({
                            "id": wid,
                            "start": round(float(w.start), 3),
                            "end": round(float(w.end), 3),
                            "text": fix_text(t),
                            "prob": round(float(w.probability), 3),
                        })
                        wid += 1
                else:
                    words.append({
                        "id": wid, "start": round(float(seg.start), 3),
                        "end": round(float(seg.end), 3),
                        "text": fix_text(seg.text.strip()), "prob": 1.0,
                    })
                    wid += 1
            sys.stderr.write(f"[transcribe] OK device={dev} lang={info.language} words={len(words)}\n")
            return words, dev, info.language
        except Exception as e:
            tried.append(f"{dev}/{ct}: {type(e).__name__}: {str(e)[:160]}")
            sys.stderr.write(f"[transcribe] FAIL {dev}: {e}\n")
            continue
    raise RuntimeError("Не удалось распознать ни на одном устройстве:\n" + "\n".join(tried))


def transcribe_file(src, workdir, model_size="large-v3", language="ru", device="auto"):
    """Полный шаг: аудио -> ASR -> words.json. Возвращает метрики."""
    import time
    src, workdir = Path(src), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    _add_nvidia_dlls()
    wav = workdir / "audio16k.wav"
    t0 = time.monotonic()
    if not wav.exists():
        extract_audio(str(src), str(wav))
    t1 = time.monotonic()
    words, dev, lang = transcribe(str(wav), model_size, language, device)
    t2 = time.monotonic()
    out = workdir / "words.json"
    out.write_text(json.dumps(
        {"device": dev, "language": lang, "source": str(src.resolve()), "words": words},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "words": len(words), "device": dev, "language": lang,
            "duration": words[-1]["end"] if words else 0.0,
            "wall_extract_s": round(t1 - t0, 1), "wall_asr_s": round(t2 - t1, 1),
            "out": str(out)}
