"""Рендер HyperFrames-блоков (моушн-графика на HTML/CSS/GSAP) как клипов для
монтажа. Блок = самодостаточный HyperFrames-проект в engine/hyperframes/<name>/;
index.html генерится на лету из данных фразы, затем `npx hyperframes render`
пишет mp4. Клип входит в пайплайн как обычный fullscreen-биролл (effect.src).

Кроме базовых `task_list`, `stat_number` и `before_after`, Visual Director
использует пять assetless semantic blocks: `complexity_cloud`, `persona_card`,
`value_layers`, `concept_nodes`, `sequence_flow`. Все получают только
валидированные данные canonical edit_plan и не ищут внешние ассеты.

Рендер тяжёлый (headless-браузер + ffmpeg, ~40с) и требует Node/npx (GSAP всё
ещё с CDN; шрифты self-hosted через data-URI, см. _fonts_css). Вызывается
опционально с graceful-фолбэком: если рендер не удался (нет node, таймаут) —
сегмент остаётся встроенным эффектом.
"""
from __future__ import annotations

import base64
import functools
import html as _html
import subprocess
from pathlib import Path

HF_DIR = Path(__file__).resolve().parents[2] / "hyperframes"
_HF_VERSION = "0.7.70"

# Self-hosted шрифты (Unbounded/Manrope, кириллица+латиница) — встраиваются в
# каждый блок как @font-face data-URI, чтобы рендер не ходил в Google Fonts
# (детерминизм + работа офлайн). Файлы в engine/hyperframes/_fonts/.
_FONTS_DIR = HF_DIR / "_fonts"
_FONT_RANGES = {
    "latin": "U+0000-00FF, U+0131, U+0152-0153, U+2000-206F, U+2074, U+20AC, U+2122, U+2212, U+2215",
    "cyrillic": "U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
}


@functools.lru_cache(maxsize=1)
def _fonts_css() -> str:
    """@font-face с data-URI для всех woff2 в _fonts/ (имя family-weight-subset)."""
    faces = []
    for f in sorted(_FONTS_DIR.glob("*.woff2")):
        fam, wght, subset = f.stem.rsplit("-", 2)
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{fam.capitalize()}';font-style:normal;"
            f"font-weight:{wght};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{_FONT_RANGES.get(subset, '')};}}")
    return "\n      ".join(faces)


# ---------- task_list ----------

_TASK_LIST_TMPL = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      __FONTS__
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
            .replace("__STAGGER__", f"{round(stagger, 3)}")
            .replace("__FONTS__", _fonts_css()))


# ---------- stat_number ----------

_STAT_TMPL = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      __FONTS__
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden;
        background: radial-gradient(120% 90% at 50% 40%, #191816 0%, #0b0b0a 58%, #060605 100%);
        font-family: "Manrope", sans-serif; }
      #root { position: relative; width: 1080px; height: 1920px; --accent: #FFE500; }
      .halo { position: absolute; top: 700px; left: 50%; transform: translateX(-50%);
        width: 820px; height: 620px;
        background: radial-gradient(closest-side, rgba(255,229,0,0.14), rgba(255,229,0,0)); filter: blur(6px); }
      .top { position: absolute; top: 620px; left: 0; width: 1080px; text-align: center;
        font-family: "Manrope"; font-weight: 700; font-size: 40px;
        letter-spacing: 7px; text-transform: uppercase; color: var(--accent); }
      .num { position: absolute; top: 720px; left: 0; width: 1080px; text-align: center;
        font-family: "Unbounded"; font-weight: 800; color: #ffffff;
        letter-spacing: -6px; line-height: 1; white-space: nowrap; }
      .num .big { font-size: 380px; }
      .num .fix { font-size: 200px; color: var(--accent); letter-spacing: -4px; }
      .bottom { position: absolute; top: 1240px; left: 140px; width: 800px; text-align: center;
        font-family: "Unbounded"; font-weight: 600; font-size: 58px;
        color: #f2f2ee; letter-spacing: -0.5px; line-height: 1.12; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__" data-width="1080" data-height="1920">
      <div id="halo" class="halo clip" data-start="0" data-duration="__DUR__" data-track-index="0"></div>
      <div id="top" class="top clip" data-start="0" data-duration="__DUR__" data-track-index="1">__TOP__</div>
      <div id="num" class="num clip" data-start="0" data-duration="__DUR__" data-track-index="2">
        <span id="pre" class="fix">__PRE__</span><span id="big" class="big">0</span><span id="suf" class="fix">__SUF__</span>
      </div>
      <div id="bottom" class="bottom clip" data-start="0" data-duration="__DUR__" data-track-index="3">__BOTTOM__</div>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const target = __TARGET__;
      const big = document.getElementById("big");
      const counter = { n: 0 };
      const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
      tl.from("#top", { opacity: 0, y: 20, duration: 0.5 }, 0.1);
      tl.fromTo(big, { scale: 0.7, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5, ease: "back.out(1.6)" }, 0.35);
      tl.to(counter, { n: target, duration: 1.4, ease: "power2.out",
        onUpdate: () => { big.textContent = Math.round(counter.n).toString(); } }, 0.4);
      tl.from(["#pre", "#suf"], { opacity: 0, scale: 0.5, duration: 0.5, ease: "back.out(2)" }, 1.4);
      tl.from("#bottom", { opacity: 0, y: 26, duration: 0.55 }, 1.55);
      tl.to("#num", { scale: 1.05, duration: 0.2, yoyo: true, repeat: 1, ease: "power2.inOut", transformOrigin: "50% 50%" }, 1.85);
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def build_stat_number_html(duration: float, value, prefix: str = "", suffix: str = "",
                           label_top: str = "", label_bottom: str = "") -> str:
    """index.html блока stat_number: большая цифра со счётом от 0."""
    try:
        target = int(round(float(value)))
    except (TypeError, ValueError):
        target = 0
    dur = max(3.0, round(float(duration), 2))
    return (_STAT_TMPL
            .replace("__DUR__", f"{dur}")
            .replace("__TARGET__", f"{target}")
            .replace("__PRE__", _html.escape(str(prefix)))
            .replace("__SUF__", _html.escape(str(suffix)))
            .replace("__TOP__", _html.escape(str(label_top).strip()))
            .replace("__BOTTOM__", _html.escape(str(label_bottom).strip()))
            .replace("__FONTS__", _fonts_css()))


# ---------- before_after ----------

_BA_TMPL = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      __FONTS__
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden;
        background: radial-gradient(120% 90% at 50% 42%, #191816 0%, #0b0b0a 58%, #060605 100%);
        font-family: "Manrope", sans-serif; }
      #root { position: relative; width: 1080px; height: 1920px; --accent: #FFE500; }
      .card { position: absolute; left: 100px; width: 880px; padding: 60px 70px; border-radius: 44px; }
      .lbl { font-family: "Manrope"; font-weight: 700; font-size: 34px; letter-spacing: 6px;
        text-transform: uppercase; margin-bottom: 18px; }
      .val { font-family: "Unbounded"; font-weight: 700; line-height: 1.05; letter-spacing: -1px; }
      #before { top: 560px; background: rgba(255,255,255,0.05); border: 2px solid rgba(255,255,255,0.10); }
      #before .lbl { color: rgba(255,255,255,0.5); }
      #before .val { color: rgba(255,255,255,0.62); font-size: 64px; text-decoration: line-through;
        text-decoration-thickness: 4px; text-decoration-color: rgba(255,255,255,0.35); }
      .arrow { position: absolute; left: 50%; top: 852px; transform: translateX(-50%);
        width: 96px; height: 96px; border-radius: 50%; background: var(--accent);
        display: flex; align-items: center; justify-content: center; }
      .arrow svg { width: 48px; height: 48px; }
      #after { top: 1000px; background: rgba(255,229,0,0.10); border: 2px solid var(--accent);
        box-shadow: 0 0 80px rgba(255,229,0,0.14); }
      #after .lbl { color: var(--accent); }
      #after .val { color: #ffffff; font-size: 88px; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__" data-width="1080" data-height="1920">
      <div id="before" class="card clip" data-start="0" data-duration="__DUR__" data-track-index="0">
        <div class="lbl">__BLABEL__</div><div class="val">__BVALUE__</div>
      </div>
      <div id="arrow" class="arrow clip" data-start="0" data-duration="__DUR__" data-track-index="1">
        <svg viewBox="0 0 24 24" fill="none" stroke="#0b0b0a" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 5 L12 19 M6 13 L12 19 L18 13"></path>
        </svg>
      </div>
      <div id="after" class="card clip" data-start="0" data-duration="__DUR__" data-track-index="2">
        <div class="lbl">__ALABEL__</div><div class="val">__AVALUE__</div>
      </div>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
      tl.from("#before", { opacity: 0, y: -50, duration: 0.6 }, 0.1);
      tl.from("#arrow", { opacity: 0, scale: 0, duration: 0.5, ease: "back.out(2)", transformOrigin: "50% 50%" }, 0.75);
      tl.from("#after", { opacity: 0, y: 60, duration: 0.6 }, 1.05);
      tl.to("#before", { opacity: 0.55, duration: 0.5 }, 1.15);
      tl.to("#after", { scale: 1.03, duration: 0.22, yoyo: true, repeat: 1, ease: "power2.inOut", transformOrigin: "50% 50%" }, 1.7);
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def build_before_after_html(duration: float, before_value: str, after_value: str,
                            before_label: str = "было", after_label: str = "стало") -> str:
    """index.html блока before_after: карточки «было -> стало»."""
    dur = max(3.0, round(float(duration), 2))
    return (_BA_TMPL
            .replace("__DUR__", f"{dur}")
            .replace("__BLABEL__", _html.escape(str(before_label).strip() or "было"))
            .replace("__BVALUE__", _html.escape(str(before_value).strip() or "-"))
            .replace("__ALABEL__", _html.escape(str(after_label).strip() or "стало"))
            .replace("__AVALUE__", _html.escape(str(after_value).strip() or "-"))
            .replace("__FONTS__", _fonts_css()))


# ---------- Visual Director semantic blocks ----------

_DIRECTOR_TMPL = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      __FONTS__
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden;
        background: #090a0b; font-family: "Manrope", sans-serif; }
      #root { position: relative; width: 1080px; height: 1920px; overflow: hidden; }
      .backdrop { position: absolute; inset: 0;
        background:
          radial-gradient(900px 720px at 18% 15%, rgba(255,229,0,.12), transparent 66%),
          radial-gradient(760px 820px at 92% 88%, rgba(69,210,255,.08), transparent 70%),
          linear-gradient(155deg, #151616 0%, #090a0b 54%, #050606 100%); }
      .backdrop::after { content: ""; position: absolute; inset: 0; opacity: .20;
        background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
        background-size: 64px 64px; }
      .scene { position: absolute; inset: 0; color: #f8f8f4; }
      .eyebrow { color: #FFE500; font-size: 30px; font-weight: 800;
        letter-spacing: 7px; text-transform: uppercase; }
      .headline { font-family: "Unbounded"; font-size: 68px; line-height: 1.08;
        font-weight: 800; letter-spacing: -2px; }
      .card { border: 2px solid rgba(255,255,255,.12); border-radius: 38px;
        background: rgba(255,255,255,.055); box-shadow: 0 26px 70px rgba(0,0,0,.24); }
      __CSS__
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__"
         data-width="1080" data-height="1920">
      <div id="director-backdrop" class="backdrop clip" data-start="0" data-duration="__DUR__" data-track-index="0"></div>
      <main id="director-scene" class="scene clip" data-start="0" data-duration="__DUR__" data-track-index="1">
        __BODY__
      </main>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
      __SCRIPT__
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def _director_html(duration: float, body: str, css: str, script: str) -> str:
    dur = max(3.0, round(float(duration), 2))
    return (_DIRECTOR_TMPL
            .replace("__DUR__", f"{dur}")
            .replace("__BODY__", body)
            .replace("__CSS__", css)
            .replace("__SCRIPT__", script)
            .replace("__FONTS__", _fonts_css()))


def _clean_items(items, limit: int = 5) -> list[str]:
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    return values[:limit] or ["—"]


def build_complexity_cloud_html(duration: float, title: str, items: list[str],
                                resolution: str) -> str:
    """Шумные решения каскадом уступают место одной ясной основе."""
    chips = "".join(
        f'<div class="chip chip-{idx + 1}">{_html.escape(item)}</div>'
        for idx, item in enumerate(_clean_items(items, 5))
    )
    body = (
        '<section class="cloud">'
        f'<div class="eyebrow">{_html.escape(str(title).strip())}</div>'
        f'<div class="chips">{chips}</div></section>'
        '<section class="resolution card">'
        '<div class="mark">→</div>'
        f'<div class="resolution-text">{_html.escape(str(resolution).strip())}</div>'
        '</section>'
    )
    css = """
      .cloud { position:absolute; left:80px; top:390px; width:920px; height:1040px; }
      .cloud .eyebrow { text-align:center; margin-bottom:100px; }
      .chips { position:relative; height:760px; }
      .chip { position:absolute; padding:30px 42px; border-radius:28px;
        border:2px solid rgba(255,255,255,.18); background:rgba(255,255,255,.07);
        font-family:"Unbounded"; font-size:38px; font-weight:650; white-space:nowrap; }
      .chip-1 { left:20px; top:30px; transform:rotate(-4deg); }
      .chip-2 { right:10px; top:205px; transform:rotate(3deg); }
      .chip-3 { left:110px; top:405px; transform:rotate(-2deg); }
      .chip-4 { right:85px; top:595px; transform:rotate(4deg); }
      .chip-5 { left:285px; top:690px; }
      .resolution { position:absolute; left:90px; top:610px; width:900px;
        min-height:520px; padding:80px 72px; border-color:#FFE500;
        background:rgba(255,229,0,.09); display:flex; flex-direction:column;
        justify-content:center; align-items:center; text-align:center; }
      .mark { color:#FFE500; font-size:90px; line-height:1; margin-bottom:40px; }
      .resolution-text { font-family:"Unbounded"; font-size:70px; line-height:1.1;
        font-weight:800; letter-spacing:-2px; }
    """
    swap = max(1.65, min(3.4, float(duration) * .48))
    script = f"""
      tl.fromTo(".cloud .eyebrow", {{opacity:0, y:-24}},
        {{opacity:1, y:0, duration:.5}}, .08);
      tl.fromTo(".chip", {{opacity:0, y:90, scale:.86}},
        {{opacity:1, y:0, scale:1, duration:.55, stagger:.16}}, .35);
      tl.to(".cloud", {{opacity:0, scale:.72, duration:.46, ease:"power2.in"}}, {swap:.3f});
      tl.fromTo(".resolution", {{opacity:0, scale:.72}},
        {{opacity:1, scale:1, duration:.58, ease:"back.out(1.45)"}}, {swap + .18:.3f});
    """
    return _director_html(duration, body, css, script)


def build_persona_card_html(duration: float, title: str, items: list[str]) -> str:
    """Карточка человека: контекст, жизнь и боль вместо talking head."""
    rows = "".join(
        f'<div class="persona-row"><span>{idx + 1:02d}</span>'
        f'<strong>{_html.escape(item)}</strong></div>'
        for idx, item in enumerate(_clean_items(items, 4))
    )
    body = (
        '<section class="persona">'
        '<div class="avatar-mark">Ч</div>'
        f'<div class="eyebrow">{_html.escape(str(title).strip())}</div>'
        f'<div class="persona-rows">{rows}</div></section>'
    )
    css = """
      .persona { position:absolute; left:80px; top:360px; width:920px; padding:70px;
        border:2px solid rgba(255,229,0,.48); border-radius:50px;
        background:linear-gradient(145deg,rgba(255,229,0,.10),rgba(255,255,255,.035)); }
      .avatar-mark { width:160px; height:160px; margin:0 auto 48px; border-radius:50%;
        display:flex; align-items:center; justify-content:center; color:#0a0a08;
        background:#FFE500; font-family:"Unbounded"; font-size:76px; font-weight:800; }
      .persona .eyebrow { text-align:center; margin-bottom:52px; }
      .persona-row { min-height:150px; display:flex; align-items:center; gap:34px;
        border-top:2px solid rgba(255,255,255,.11); }
      .persona-row span { color:#FFE500; font-family:"Unbounded"; font-size:30px; }
      .persona-row strong { font-family:"Unbounded"; font-size:48px; line-height:1.08; }
    """
    script = """
      tl.fromTo(".avatar-mark", {opacity:0, scale:.68},
        {opacity:1, scale:1, duration:.58, ease:"back.out(1.55)"}, .08);
      tl.fromTo(".persona .eyebrow", {opacity:0, y:24},
        {opacity:1, y:0, duration:.46}, .28);
      tl.fromTo(".persona-row", {opacity:0, y:44, scale:.94},
        {opacity:1, y:0, scale:1, duration:.48, stagger:.18, ease:"back.out(1.25)"}, .56);
    """
    return _director_html(duration, body, css, script)


def build_value_layers_html(duration: float, title: str, offer: str,
                            actual: str) -> str:
    """Scale-swap от формального продукта к покупаемой ценности."""
    body = (
        f'<div class="eyebrow value-title">{_html.escape(str(title).strip())}</div>'
        '<section class="layer offer card" data-layout-allow-overlap><div class="layer-label">ФОРМАЛЬНО</div>'
        f'<div class="layer-value">{_html.escape(str(offer).strip())}</div></section>'
        '<div class="swap-arrow">↓</div>'
        '<section class="layer actual card" data-layout-allow-overlap><div class="layer-label">НА САМОМ ДЕЛЕ</div>'
        f'<div class="layer-value">{_html.escape(str(actual).strip())}</div></section>'
    )
    css = """
      .value-title { position:absolute; top:360px; left:100px; width:880px; text-align:center; }
      .layer { position:absolute; left:90px; top:610px; width:900px; min-height:520px;
        padding:72px; display:flex; flex-direction:column; justify-content:center;
        text-align:center; transform-origin:50% 50%; }
      .layer-label { color:rgba(255,255,255,.55); font-size:30px; font-weight:800;
        letter-spacing:7px; margin-bottom:40px; }
      .layer-value { font-family:"Unbounded"; font-size:70px; font-weight:800; line-height:1.08; }
      .actual { border-color:#FFE500; background:rgba(255,229,0,.10); }
      .actual .layer-label { color:#FFE500; }
      .swap-arrow { position:absolute; left:490px; top:1190px; color:#FFE500;
        font-size:90px; line-height:1; }
    """
    swap = max(1.45, min(3.4, float(duration) * .46))
    script = f"""
      tl.fromTo(".value-title", {{opacity:0, y:-24}}, {{opacity:1, y:0, duration:.5}}, .08);
      tl.fromTo(".offer", {{opacity:0, scale:.72}}, {{opacity:1, scale:1, duration:.58}}, .34);
      tl.fromTo(".swap-arrow", {{opacity:0, y:-30}}, {{opacity:1, y:0, duration:.4}}, {swap - .34:.3f});
      tl.to(".offer", {{opacity:0, scale:.72, duration:.42, ease:"power2.in"}}, {swap:.3f});
      tl.fromTo(".actual", {{opacity:0, scale:1.28}},
        {{opacity:1, scale:1, duration:.58, ease:"back.out(1.35)"}}, {swap + .14:.3f});
    """
    return _director_html(duration, body, css, script)


def build_concept_nodes_html(duration: float, title: str,
                             items: list[str]) -> str:
    """Три опорных понятия расходятся от центрального тезиса."""
    values = _clean_items(items, 3)
    nodes = "".join(
        f'<div class="concept-node node-{idx + 1}">{_html.escape(item)}</div>'
        for idx, item in enumerate(values)
    )
    lines = "".join(f'<div class="connector line-{idx + 1}"></div>'
                    for idx in range(len(values)))
    body = (
        f'<div class="hub">{_html.escape(str(title).strip())}</div>'
        f'<div class="connectors">{lines}</div><div class="nodes">{nodes}</div>'
    )
    css = """
      .hub { position:absolute; left:290px; top:770px; width:500px; height:300px;
        display:flex; align-items:center; justify-content:center; padding:50px;
        border-radius:50%; border:3px solid #FFE500; background:rgba(255,229,0,.10);
        color:#fff; text-align:center; font-family:"Unbounded"; font-size:48px;
        line-height:1.08; font-weight:800; z-index:3; }
      .concept-node { position:absolute; width:350px; min-height:170px; padding:38px 24px;
        display:flex; align-items:center; justify-content:center; text-align:center;
        border:2px solid rgba(255,255,255,.18); border-radius:34px;
        background:#171819; font-family:"Unbounded"; font-size:46px; font-weight:750; z-index:2; }
      .node-1 { left:365px; top:350px; }
      .node-2 { left:80px; top:1250px; }
      .node-3 { right:80px; top:1250px; }
      .connector { position:absolute; left:540px; top:920px; width:330px; height:4px;
        background:linear-gradient(90deg,#FFE500,rgba(255,229,0,.12));
        transform-origin:left center; z-index:1; }
      .line-1 { transform:rotate(-90deg); width:400px; }
      .line-2 { transform:rotate(130deg); width:470px; }
      .line-3 { transform:rotate(50deg); width:470px; }
    """
    script = """
      tl.fromTo(".hub", {opacity:0, scale:.66},
        {opacity:1, scale:1, duration:.6, ease:"back.out(1.45)"}, .08);
      tl.fromTo(".connector", {scaleX:0}, {scaleX:1, duration:.48, stagger:.14}, .48);
      tl.fromTo(".concept-node", {opacity:0, scale:.7},
        {opacity:1, scale:1, duration:.52, stagger:.16, ease:"back.out(1.35)"}, .7);
    """
    return _director_html(duration, body, css, script)


def build_sequence_flow_html(duration: float, title: str,
                             items: list[str]) -> str:
    """Порядок из трёх шагов, раскрывающийся сверху вниз."""
    values = _clean_items(items, 4)
    rows = "".join(
        f'<div class="flow-step"><span>{idx + 1:02d}</span>'
        f'<strong>{_html.escape(item)}</strong></div>'
        + ('<div class="flow-arrow">↓</div>' if idx < len(values) - 1 else '')
        for idx, item in enumerate(values)
    )
    body = (
        f'<header class="flow-title"><div class="eyebrow">ПОРЯДОК РЕШАЕТ</div>'
        f'<div class="headline">{_html.escape(str(title).strip())}</div></header>'
        f'<section class="flow">{rows}</section>'
    )
    css = """
      .flow-title { position:absolute; left:80px; top:280px; width:920px; text-align:center; }
      .flow-title .eyebrow { margin-bottom:30px; }
      .flow { position:absolute; left:120px; top:650px; width:840px; }
      .flow-step { min-height:220px; padding:44px 54px; display:flex; align-items:center;
        gap:42px; border:2px solid rgba(255,255,255,.14); border-radius:38px;
        background:rgba(255,255,255,.055); }
      .flow-step span { width:100px; height:100px; flex:0 0 100px; border-radius:50%;
        display:flex; align-items:center; justify-content:center; background:#FFE500;
        color:#0a0a08; font-family:"Unbounded"; font-size:36px; font-weight:800; }
      .flow-step strong { font-family:"Unbounded"; font-size:58px; font-weight:800; }
      .flow-arrow { height:92px; display:flex; align-items:center; justify-content:center;
        color:#FFE500; font-size:66px; line-height:1; }
    """
    script = """
      tl.fromTo(".flow-title .eyebrow", {opacity:0, y:-28},
        {opacity:1, y:0, duration:.45}, .08);
      tl.fromTo(".flow-title .headline", {opacity:0, y:32},
        {opacity:1, y:0, duration:.52}, .25);
      tl.fromTo(".flow-step", {opacity:0, y:72, scale:.9},
        {opacity:1, y:0, scale:1, duration:.52, stagger:.26, ease:"back.out(1.3)"}, .62);
      tl.fromTo(".flow-arrow", {opacity:0, scaleY:0},
        {opacity:1, scaleY:1, duration:.3, stagger:.26}, .91);
    """
    return _director_html(duration, body, css, script)


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
    "stat_number": ("stat_number", build_stat_number_html),
    "before_after": ("before_after", build_before_after_html),
    "complexity_cloud": ("complexity_cloud", build_complexity_cloud_html),
    "persona_card": ("persona_card", build_persona_card_html),
    "value_layers": ("value_layers", build_value_layers_html),
    "concept_nodes": ("concept_nodes", build_concept_nodes_html),
    "sequence_flow": ("sequence_flow", build_sequence_flow_html),
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
