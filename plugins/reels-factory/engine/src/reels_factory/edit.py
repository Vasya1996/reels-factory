"""Монтажный слой поверх готовых фрагментов: джамп-каты, цвет, зерно.

Джамп-кат — вырезанная пауза внутри одного плана: уходят вдохи, «эээ» и
провисания между фразами, речь становится плотной. Это первое, что делает
монтажёр, и первое, чего не хватает синтезированной речи: TTS оставляет ровные
паузы там, где живой человек их проглатывает.

Резать умеет auto-editor (WyattBlue/auto-editor) — зрелый инструмент поверх
ffmpeg, режет видео и звук одним проходом, поэтому картинка и голос не могут
разъехаться. Ставится как обычная зависимость: `pip install auto-editor`.

Порядок в конвейере важен: джамп-каты применяются к фрагментам ДО assemble.
Тогда `media_dur` меряет уже подрезанные фрагменты, `retime_scenario` строит
сетку по фактическим длительностям, и субтитры со вставками сами встают на
новые времена — отдельной синхронизации не нужно.

Все шаги — опциональные и по умолчанию выключены (edit.* в config.yaml):
включаются флагом, откатываются флагом.
"""
import shutil
import subprocess
from pathlib import Path

# Порог тишины: доля от пика. 4% — тише этого считаем паузой.
DEFAULT_SILENCE_THRESHOLD = 0.04
# Запас вокруг речи: не срезать дыхание вплотную к словам, иначе речь звучит
# рублено и согласные на стыках проглатываются.
DEFAULT_MARGIN_S = 0.15
# Совсем короткие паузы (запятая, смысловой акцент) не трогаем — это ритм речи,
# а не провисание.
DEFAULT_MIN_SILENCE_S = 0.35


class EditError(RuntimeError):
    pass


def _auto_editor_bin() -> str:
    exe = shutil.which("auto-editor")
    if exe:
        return exe
    raise EditError(
        "auto-editor не найден: установи `pip install auto-editor` "
        "или выключи edit.jump_cuts в config.yaml"
    )


def jump_cut(src: Path, out: Path, *,
             threshold: float = DEFAULT_SILENCE_THRESHOLD,
             margin_s: float = DEFAULT_MARGIN_S,
             min_silence_s: float = DEFAULT_MIN_SILENCE_S,
             run=None) -> Path:
    """Вырезать паузы из фрагмента. Возвращает путь к результату.

    src не меняется — результат пишется в out (удобно для сравнения до/после).
    """
    src, out = Path(src), Path(out)
    if not src.exists():
        raise EditError(f"нет исходного фрагмента: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _auto_editor_bin(), str(src),
        "--edit", f"audio:threshold={threshold}",
        "--margin", f"{margin_s}s",
        "--output", str(out),
        "--no-open",
    ]
    runner = run or _run
    runner(cmd)
    if not out.exists():
        raise EditError(f"auto-editor не создал файл: {out}")
    return out


def jump_cut_fragments(frags: list, rdir: Path, **kw) -> list:
    """Прогнать джамп-каты по всем фрагментам блока. Порядок сохраняется.

    Фрагмент, из которого нечего вырезать, auto-editor возвращает как есть —
    отдельной ветки на этот случай не нужно.
    """
    rdir = Path(rdir)
    out = []
    for i, frag in enumerate(frags):
        frag = Path(frag)
        out.append(jump_cut(frag, rdir / f"{frag.stem}_cut{frag.suffix}", **kw))
    return out


def apply_finish(src: Path, out: Path, *, grade: bool = False, grain: bool = False,
                 run=None) -> Path:
    """Цвет и зерно на готовом ролике — для проверки шагов на своём материале
    (в основном конвейере то же самое делается одним проходом внутри assemble).
    Звук копируется как есть."""
    from reels_factory.compose import build_finish_filter
    from reels_factory.config import FFMPEG

    src, out = Path(src), Path(out)
    if not src.exists():
        raise EditError(f"нет исходного файла: {src}")
    vf = build_finish_filter(grade, grain)
    if not vf:
        raise EditError("нечего применять: включи grade и/или grain")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "copy", str(out)]
    (run or _run)(cmd)
    return out


def _run(cmd: list) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        raise EditError(
            f"auto-editor упал (код {p.returncode}): {(p.stderr or '')[:500]}")
