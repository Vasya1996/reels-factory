"""Рендер HyperFrames-блоков (моушн-графика на HTML/CSS/GSAP) как клипов для
монтажа. Блок = самодостаточный HyperFrames-проект в engine/hyperframes/<name>/;
index.html генерится на лету из данных фразы, затем `npx hyperframes render`
пишет mp4. Клип входит в пайплайн как обычный fullscreen-биролл (effect.src).

Пока реализован один блок — `task_list` (перечисление -> анимированный список),
замена встроенного chart_bars. Каркас общий: добавить блок = добавить проект +
builder HTML + запись в BLOCKS.

Рендер тяжёлый (headless-браузер + ffmpeg, ~40с) и требует Node/npx + сеть
(шрифты). Поэтому вызывается опционально с graceful-фолбэком: если рендер не
удался (нет node, сети, таймаут) — сегмент остаётся встроенным эффектом.
"""
from __future__ import annotations

import html as _html
import subprocess
from pathlib import Path

HF_DIR = Path(__file__).resolve().parents[2] / "hyperframes"
_HF_VERSION = "0.7.70"


# ---------- task_list ----------

_TASK_LIST_TMPL = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      @import url("https://fonts.googleapis.com/css2?family=Unbounded:wght@600;700;800&family=Manrope:wght@500;700&display=swap");
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        width: 1080px; height: 1920px; overflow: hidden;
        background: radial-gradient(120% 90% at 50% 12%, #1b1a16 0%, #0b0b0a 55%, #060605 100%);
        font-family: "Manrope", sans-serif;
      }
      #root { position: relative; width: 1080px; height: 1920px; }
      .glow { position: absolute; top: 200px; left: 50%; transform: translateX(-50%);
        width: 900px; height: 520px;
        background: radial-gradient(closest-side, rgba(255,229,0,0.16), rgba(255,229,0,0)); filter: blur(8px); }
      .title { position: absolute; top: 360px; left: 90px; width: 920px;
        font-family: "Unbounded"; font-weight: 800; font-size: 70px;
        line-height: 1.05; color: #ffffff; letter-spacing: -1.5px; }
      .underline { position: absolute; top: 548px; left: 92px;
        width: 300px; height: 10px; border-radius: 6px; background: #FFE500; transform-origin: left center; }
      .list { position: absolute; top: 730px; left: 90px; width: 900px; }
      .row { position: relative; display: flex; align-items: center; gap: 34px; height: 168px; }
      .divider { position: absolute; left: 0; bottom: 0; width: 900px; height: 2px;
        background: linear-gradient(90deg, rgba(255,255,255,0.22), rgba(255,255,255,0)); transform-origin: left center; }
      .badge { flex: 0 0 96px; width: 96px; height: 96px; border-radius: 26px;
        display: flex; align-items: center; justify-content: center;
        background: rgba(255,229,0,0.12); border: 2px solid rgba(255,229,0,0.55);
        font-family: "Unbounded"; font-weight: 700; font-size: 46px; color: #FFE500; }
      .label { font-family: "Unbounded"; font-weight: 600; font-size: 52px; color: #f2f2ee; letter-spacing: -0.5px; }
      .row.more .badge { background: #FFE500; border-color: #FFE500; color: #0b0b0a; font-size: 60px; }
      .row.more .label { color: #FFE500; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__"
         data-width="1080" data-height="1920">
      <div id="glow" class="glow clip" data-start="0" data-duration="__DUR__" data-track-index="0"></div>
      <div id="title" class="title clip" data-start="0" data-duration="__DUR__" data-track-index="1">__TITLE__</div>
      <div id="underline" class="underline clip" data-start="0" data-duration="__DUR__" data-track-index="2"></div>
      <div id="list" class="list clip" data-start="0" data-duration="__DUR__" data-track-index="3">
__ROWS__
      </div>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
      tl.from(".title", { opacity: 0, y: 40, duration: 0.7 }, 0.15);
      tl.fromTo(".underline", { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "power2.inOut" }, 0.5);
      const rows = gsap.utils.toArray(".row");
      const STAGGER = __STAGGER__;
      rows.forEach((row, i) => {
        const t = 1.0 + i * STAGGER;
        tl.from(row.querySelector(".divider"), { scaleX: 0, duration: 0.4, ease: "power2.out" }, t);
        tl.from(row.querySelector(".badge"), { opacity: 0, scale: 0.5, duration: 0.5, ease: "back.out(2)" }, t + 0.05);
        tl.from(row.querySelector(".label"), { opacity: 0, x: -40, duration: 0.5 }, t + 0.12);
      });
      const more = document.querySelector(".row.more .badge");
      if (more) tl.to(more, { scale: 1.12, duration: 0.22, yoyo: true, repeat: 1, ease: "power2.inOut" }, "+=0.1");
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def _row_html(idx: int, label: str, more: bool) -> str:
    cls = "row more" if more else "row"
    badge = "+" if more else f"{idx + 1:02d}"
    label = _html.escape(label.strip())
    return (f'        <div class="{cls}" data-i="{idx}">\n'
            f'          <div class="divider"></div>\n'
            f'          <div class="badge">{badge}</div><div class="label">{label}</div>\n'
            f'        </div>')


def build_task_list_html(title: str, items: list[str], duration: float) -> str:
    """Собрать index.html блока task_list из заголовка и пунктов."""
    items = [str(x).strip() for x in items if str(x).strip()][:5]
    if not items:
        items = ["-"]
    # последний пункт с «+» -> акцентная строка «ещё»
    rows = []
    for i, label in enumerate(items):
        more = label.startswith("+") or (i == len(items) - 1 and len(items) >= 4)
        rows.append(_row_html(i, label.lstrip("+ ").strip() or label, more))
    n = len(items)
    dur = max(3.0, round(float(duration), 2))
    # разложить появление пунктов в пределах окна (голова 1.0с + хвост ~1.2с)
    stagger = max(0.28, min(0.62, (dur - 2.2) / max(1, n)))
    return (_TASK_LIST_TMPL
            .replace("__DUR__", f"{dur}")
            .replace("__TITLE__", _html.escape(title.strip() or "СПИСОК"))
            .replace("__ROWS__", "\n".join(rows))
            .replace("__STAGGER__", f"{round(stagger, 3)}"))


# ---------- рендер ----------

def _default_runner(project_dir: Path, out_path: Path, timeout: int) -> None:
    """Запустить `npx hyperframes render --output <out>` в проекте блока."""
    subprocess.run(
        f'npx --yes hyperframes@{_HF_VERSION} render --output "{out_path}"',
        cwd=str(project_dir), shell=True, check=True, timeout=timeout,
    )


# name -> (project subdir, HTML builder(**variables, duration))
BLOCKS = {
    "task_list": ("task_list", build_task_list_html),
}


def render_block(block: str, variables: dict, duration: float, out_path,
                 *, runner=None, timeout: int = 240) -> Path:
    """Отрендерить HyperFrames-блок в mp4 по имени и переменным.

    variables — данные блока (для task_list: {"title", "items"}). Пишет
    index.html проекта и запускает рендер. Бросает при неизвестном блоке или
    падении рендера — вызывающий ловит и делает фолбэк.
    """
    if block not in BLOCKS:
        raise ValueError(f"неизвестный HyperFrames-блок: {block!r}")
    subdir, builder = BLOCKS[block]
    project = HF_DIR / subdir
    if not project.exists():
        raise RuntimeError(f"проект блока не найден: {project}")
    html_text = builder(duration=duration, **variables)
    (project / "index.html").write_text(html_text, encoding="utf-8")
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    (runner or _default_runner)(project, out_path, timeout)
    if not out_path.exists():
        raise RuntimeError(f"рендер блока не создал файл: {out_path}")
    return out_path
