"""Экранный маршрут: браузер сам проходит путь, мы записываем это видео.

Закрывает класс вставок «покажи, как до этого дойти»: ввод запроса, выбор
ссылки, переход, прокрутка. Браузер берём тот, который движок уже скачал для
рендера — второй копии Chrome на диске не появляется.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from reels_factory.hyperframes_blocks import _HF_VERSION

STEP_TYPES = {"goto", "type", "click", "scroll", "wait"}
ENGINE_DIR = Path(__file__).resolve().parents[2]


def chrome_path() -> str:
    """Путь к браузеру, который движок скачал для рендера."""
    root = Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell"
    candidates = sorted(root.glob("**/chrome-headless-shell*"))
    if not candidates:
        raise RuntimeError(
            "браузер движка не найден; выполни "
            f"npx hyperframes@{_HF_VERSION} browser install")
    return str(candidates[-1])


def validate_steps(steps: list[dict]) -> None:
    if not steps:
        raise ValueError("пустой маршрут")
    required = {"goto": "url", "type": "text", "click": "selector",
                "scroll": "pixels", "wait": "seconds"}
    for step in steps:
        kind = step.get("type")
        if kind not in STEP_TYPES:
            raise ValueError(f"неизвестный шаг: {kind!r}")
        if required[kind] not in step:
            raise ValueError(f"шаг {kind}: нет поля {required[kind]}")
    if steps[0].get("type") != "goto":
        raise ValueError("маршрут обязан начинаться с перехода на страницу")


def build_script(steps: list[dict], *, width: int, height: int,
                 browser_path: str, frames_dir) -> str:
    """Код для браузера: пройти маршрут и снять кадры в frames_dir."""
    validate_steps(steps)
    frames = json.dumps(str(Path(frames_dir).as_posix()))
    lines = [
        "const puppeteer = require('puppeteer-core');",
        "(async () => {",
        # именно 'shell': chrome-headless-shell не понимает --headless=new
        f"  const browser = await puppeteer.launch({{headless: 'shell', "
        f"executablePath: {json.dumps(browser_path)}, "
        f"args: ['--no-sandbox', '--window-size={width},{height}']}});",
        "  const page = await browser.newPage();",
        f"  await page.setViewport({{width: {width}, height: {height}}});",
        f"  const dir = {frames};",
        "  let frame = 0;",
        "  const shot = async () => { await page.screenshot("
        "{path: `${dir}/${String(frame++).padStart(5,'0')}.png`}); };",
    ]
    for step in steps:
        kind = step["type"]
        if kind == "goto":
            lines.append(f"  await page.goto({json.dumps(step['url'])}, "
                         "{waitUntil: 'networkidle2'});")
            lines.append("  for (let i = 0; i < 15; i++) await shot();")
        elif kind == "type":
            lines.append(f"  await page.click({json.dumps(step['selector'])});")
            lines.append(f"  for (const ch of {json.dumps(step['text'])}) "
                         "{ await page.keyboard.type(ch); await shot(); }")
        elif kind == "click":
            lines.append(f"  await page.click({json.dumps(step['selector'])});")
            lines.append("  await page.waitForNetworkIdle({idleTime: 500}).catch(() => {});")
            lines.append("  for (let i = 0; i < 15; i++) await shot();")
        elif kind == "scroll":
            lines.append(f"  for (let y = 0; y < {int(step['pixels'])}; y += 24) "
                         "{ await page.evaluate(() => window.scrollBy(0, 24)); await shot(); }")
        elif kind == "wait":
            lines.append(f"  for (let i = 0; i < {int(float(step['seconds']) * 30)}; i++) "
                         "await shot();")
    lines += ["  await browser.close();", "})();"]
    return "\n".join(lines)


def record_route(steps: list[dict], out_mp4, *, width: int = 1080,
                 height: int = 1920, fps: int = 30) -> Path:
    """Пройти маршрут и собрать кадры в видео."""
    from reels_factory.config import FFMPEG

    out_mp4 = Path(out_mp4).resolve()
    frames_dir = out_mp4.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    script = out_mp4.parent / "route.js"
    script.write_text(
        build_script(steps, width=width, height=height,
                     browser_path=chrome_path(), frames_dir=frames_dir),
        encoding="utf-8")

    # запускаем из каталога движка с NODE_PATH, иначе require не найдёт puppeteer-core
    env = os.environ.copy()
    env["NODE_PATH"] = str(ENGINE_DIR / "node_modules")
    result = subprocess.run(["node", str(script)], cwd=str(ENGINE_DIR),
                            capture_output=True, text=True, encoding="utf-8", env=env)
    if result.returncode != 0:
        raise RuntimeError(f"маршрут не прошёл: {(result.stderr or '')[:400]}")

    subprocess.run(
        [FFMPEG, "-y", "-framerate", str(fps), "-i", str(frames_dir / "%05d.png"),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out_mp4)],
        check=True, capture_output=True)
    return out_mp4
