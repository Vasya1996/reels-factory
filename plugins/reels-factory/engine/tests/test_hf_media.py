"""Отсев вставок: их поиск ранжирует, мы только вычёркиваем негодных."""
import pytest

from reels_factory import hf_media
from reels_factory.hf_media import (
    _claim, candidate_problem, resolve_all, scan_ocr_rows,
)

FULL = {"left": 0, "top": 0, "width": 1080, "height": 1920}


def _cand(id_: str, width=1200, height=1800, **over):
    cand = {"id": id_, "url": f"https://cdn/{id_}.jpg",
            "width": width, "height": height, "is_transparent": False}
    cand.update(over)
    return cand


# ---------- отсев по метаданным ----------

def test_прозрачный_кандидат_вычёркивается():
    assert "прозрачный" in candidate_problem(
        _cand("a", is_transparent=True), FULL)


def test_мелкий_кандидат_вычёркивается():
    assert "мелкий" in candidate_problem(_cand("a", 200, 300), FULL)


def test_растяжение_в_мыло_вычёркивается():
    """Прогон 15: файл 500x281 закрывал кадр 1080x1920 — растяжение в 6,8 раза."""
    assert "мыло" in candidate_problem(_cand("a", 500, 281), FULL)


def test_кандидат_без_размеров_судится_после_скачивания():
    assert candidate_problem(_cand("a", width=None, height=None), FULL) is None


def test_большой_кандидат_проходит():
    assert candidate_problem(_cand("a", 2048, 1365), FULL) is None


# ---------- выбор кандидата ----------

def test_берётся_первый_годный_в_их_порядке():
    """Ранжирование — их; мы не пересортировываем, только вычёркиваем."""
    picked = _claim({"rect": FULL}, [_cand("мелкий", 300, 200), _cand("б"),
                                     _cand("в")], set())
    assert picked["id"] == "б"


def test_занятый_снимок_не_ставится_дважды():
    """Прогон 15: один файл под двумя именами в двух сценах."""
    picked = _claim({"rect": FULL}, [_cand("а"), _cand("б")], {"а"})
    assert picked["id"] == "б"


def test_запасной_круг_снимает_вето_растяжения():
    """Сцене без ведущей вставка обязательна: мыло лучше чёрного кадра."""
    candidates = [_cand("а", 500, 281)]
    assert _claim({"rect": FULL}, candidates, set()) is None
    assert _claim({"rect": FULL}, candidates, set(),
                  relaxed=True)["id"] == "а"


def test_запасной_круг_не_берёт_прозрачное_и_совсем_мелкое():
    candidates = [_cand("а", is_transparent=True), _cand("б", 150, 100)]
    assert _claim({"rect": FULL}, candidates, set(), relaxed=True) is None


# ---------- OCR ----------

_TSV_HEAD = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
             "left\ttop\twidth\theight\tconf\ttext")


def _tsv(*rows):
    return "\n".join([_TSV_HEAD, *rows])


def _row(text, conf=90.0, height=100):
    return f"5\t1\t1\t1\t1\t1\t10\t10\t200\t{height}\t{conf}\t{text}"


def test_водяной_знак_ловится_по_словарю():
    """Кадры прогона 15: сетка dreamstime поперёк снимка."""
    verdict = scan_ocr_rows(_tsv(_row("dreamstime.com", conf=55, height=20)),
                            1365)
    assert verdict and "водяной знак" in verdict


def test_крупный_текст_на_фотографии_ловится():
    verdict = scan_ocr_rows(
        _tsv(_row("Success"), _row("Mindset")), 1000)
    assert verdict and "читаемый текст" in verdict


def test_мелкая_вывеска_на_фоне_не_считается_текстом():
    verdict = scan_ocr_rows(
        _tsv(_row("кафе", height=15), _row("выход", height=12)), 1000)
    assert verdict is None


def test_неуверенное_распознавание_не_считается():
    verdict = scan_ocr_rows(
        _tsv(_row("шум", conf=30.0), _row("помехи", conf=12.0)), 1000)
    assert verdict is None


def test_одно_слово_не_приговор():
    assert scan_ocr_rows(_tsv(_row("Open")), 1000) is None


# ---------- подбор целиком, без сети ----------

def _wire(monkeypatch, catalog, bad_files=()):
    """Поиск и заморозка без сети: каталог задан словарём intent -> кандидаты."""
    monkeypatch.setattr(hf_media, "search_assets",
                        lambda intent, **kw: catalog.get(intent, []))
    monkeypatch.setattr(
        hf_media, "ingest",
        lambda public, url, **kw: {"ok": True,
                                   "path": ".media/images/"
                                           + url.rsplit("/", 1)[-1]})
    monkeypatch.setattr(hf_media, "insert_problem",
                        lambda path, rect=None: "мыло"
                        if any(bad in str(path) for bad in bad_files) else None)
    monkeypatch.setattr(hf_media, "text_problem", lambda path: None)
    monkeypatch.setattr(hf_media.Path, "exists", lambda self: True)


def _request(key, intent, required=False):
    return {"key": key, "type": "image", "intent": intent, "rect": FULL,
            "required": required}


def test_негодный_файл_заменяется_следующим_кандидатом(monkeypatch, tmp_path):
    _wire(monkeypatch,
          {"стол": [_cand("плохой"), _cand("хороший")]},
          bad_files=("плохой",))
    found = resolve_all(tmp_path, [_request("s-01", "стол")])
    assert found["s-01"]["file"].endswith("хороший.jpg")


def test_две_сцены_не_получают_один_снимок(monkeypatch, tmp_path):
    _wire(monkeypatch, {"стол": [_cand("общий"), _cand("второй")],
                        "стол крупнее": [_cand("общий"), _cand("третий")]})
    found = resolve_all(tmp_path, [_request("s-01", "стол"),
                                   _request("s-02", "стол крупнее")])
    assert found["s-01"]["file"].endswith("общий.jpg")
    assert found["s-02"]["file"].endswith("третий.jpg")


def test_пустой_каталог_отдаёт_ошибку_а_не_падает(monkeypatch, tmp_path):
    _wire(monkeypatch, {})
    found = resolve_all(tmp_path, [_request("s-01", "не найдётся")])
    assert "error" in found["s-01"]


# ---------- видео-бироллы ----------

def _pexels_video(vid, duration=12.0, files=None):
    return {"id": vid, "duration": duration,
            "image": f"https://images.pexels.com/{vid}.jpeg",
            "video_files": files if files is not None else [
                {"file_type": "video/mp4", "width": 1080, "height": 1920,
                 "link": f"https://videos.pexels.com/video-files/{vid}-hd.mp4"},
                {"file_type": "video/mp4", "width": 2160, "height": 3840,
                 "link": f"https://videos.pexels.com/video-files/{vid}-4k.mp4"}]}


def test_лучший_файл_ближе_к_нашей_высоте():
    """4K тянется дольше, кадр у нас 1080x1920 — берём достаточное."""
    best = hf_media._best_file(_pexels_video("а"))
    assert best["height"] == 1920


def test_горизонтальные_и_мелкие_файлы_не_берутся():
    video = _pexels_video("а", files=[
        {"file_type": "video/mp4", "width": 1920, "height": 1080,
         "link": "https://cdn/х.mp4"},
        {"file_type": "video/mp4", "width": 540, "height": 960,
         "link": "https://cdn/м.mp4"}])
    assert hf_media._best_file(video) is None


def _wire_video(monkeypatch, catalog, verdicts=None):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(hf_media, "search_pexels",
                        lambda intent, **kw: catalog.get(intent, []))
    monkeypatch.setattr(hf_media, "_download",
                        lambda url, target: target)
    monkeypatch.setattr(
        hf_media, "ingest",
        lambda public, src, **kw: {"ok": True,
                                   "path": ".media/video/"
                                           + str(src).rsplit("\\", 1)[-1]
                                                     .rsplit("/", 1)[-1]})
    monkeypatch.setattr(hf_media, "insert_problem", lambda path, rect=None: None)
    monkeypatch.setattr(hf_media, "judge_previews",
                        lambda requests, **kw: verdicts or {})
    monkeypatch.setattr(hf_media.Path, "unlink",
                        lambda self, missing_ok=False: None)
    return ThreadPoolExecutor(max_workers=2)


def _vreq(key, intent, seconds=3.0):
    return {"key": key, "type": "video", "intent": intent, "rect": FULL,
            "required": False, "seconds": seconds, "speech": "реплика"}


def _vcand(id_, duration=12.0):
    return {"id": id_, "duration": duration, "preview": f"https://p/{id_}.jpg",
            "url": f"https://v/{id_}.mp4", "width": 1080, "height": 1920,
            "is_transparent": False}


def test_вердикт_судьи_уважается(monkeypatch, tmp_path):
    with _wire_video(monkeypatch,
                     {"стол": [_vcand("первый"), _vcand("второй")]},
                     verdicts={"s-01": 1}) as pool:
        found = hf_media._resolve_videos(tmp_path, [_vreq("s-01", "стол")],
                                         pool=pool)
    assert found["s-01"]["file"].endswith("второй.mp4")


def test_null_судьи_оставляет_сцену_без_вставки(monkeypatch, tmp_path):
    """Кринж хуже отсутствия: сцену закроет ведущая."""
    with _wire_video(monkeypatch, {"стол": [_vcand("первый")]},
                     verdicts={"s-01": None}) as pool:
        found = hf_media._resolve_videos(tmp_path, [_vreq("s-01", "стол")],
                                         pool=pool)
    assert "error" in found["s-01"]


def test_один_ролик_не_ставится_в_две_сцены(monkeypatch, tmp_path):
    with _wire_video(monkeypatch,
                     {"стол": [_vcand("общий"), _vcand("другой")],
                      "стол крупно": [_vcand("общий"), _vcand("третий")]},
                     verdicts={"s-01": 0, "s-02": 0}) as pool:
        found = hf_media._resolve_videos(
            tmp_path, [_vreq("s-01", "стол"), _vreq("s-02", "стол крупно")],
            pool=pool)
    assert found["s-01"]["file"].endswith("общий.mp4")
    assert found["s-02"]["file"].endswith("третий.mp4")


def test_негодный_ролик_заменяется_следующим_кандидатом_той_же_сцены(
        monkeypatch, tmp_path):
    """Прежде такую сцену закрывала копия вставки соседней — картинка не про
    эту реплику. У сцены свои кандидаты скачаны и отсужены: берём следующего."""
    with _wire_video(monkeypatch,
                     {"стол": [_vcand("мутный"), _vcand("годный")]},
                     verdicts={"s-01": 0}) as pool:
        monkeypatch.setattr(
            hf_media, "insert_problem",
            lambda path, rect=None: ("растянут" if "мутный" in str(path)
                                     else None))
        found = hf_media._resolve_videos(tmp_path, [_vreq("s-01", "стол")],
                                         pool=pool)
    assert found["s-01"]["file"].endswith("годный.mp4")


def test_добор_не_берёт_ролик_занятый_другой_сценой(monkeypatch, tmp_path):
    with _wire_video(monkeypatch,
                     {"стол": [_vcand("общий")],
                      "рука": [_vcand("мутный"), _vcand("общий")]},
                     verdicts={"s-01": 0, "s-02": 0}) as pool:
        monkeypatch.setattr(
            hf_media, "insert_problem",
            lambda path, rect=None: ("растянут" if "мутный" in str(path)
                                     else None))
        found = hf_media._resolve_videos(
            tmp_path, [_vreq("s-01", "стол"), _vreq("s-02", "рука")], pool=pool)
    assert found["s-01"]["file"].endswith("общий.mp4")
    assert "error" in found["s-02"]


def test_телеметрия_подбора_выключена():
    """Их подбор шлёт события наружу и связывает их с почтой владельца ключей.
    Выключатель их же, и им они глушат телеметрию в собственном CI."""
    assert hf_media._node_env()["HYPERFRAMES_NO_TELEMETRY"] == "1"


def test_начертание_знака_выбирается_по_палитре(monkeypatch):
    """Их подбор всегда берёт светлое начертание (`logo-provider.mjs:130`) —
    тёмный знак под светлый фон. На тёмном ролике он тонет, поэтому пару
    начертаний спрашиваем у самого источника."""
    import json as _json

    pair = [{"title": "OpenAI", "route": {"light": "openai.svg",
                                          "dark": "openai_dark.svg"}}]

    class _Answer:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps(pair).encode("utf-8")

    monkeypatch.setattr(hf_media.urllib.request, "urlopen",
                        lambda *a, **kw: _Answer())
    assert hf_media.svgl_route("openai", dark=True) == "openai_dark.svg"
    assert hf_media.svgl_route("openai", dark=False) == "openai.svg"


def test_полноцветный_знак_один_на_любой_фон(monkeypatch):
    import json as _json

    single = [{"title": "Telegram", "route": "telegram.svg"}]

    class _Answer:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps(single).encode("utf-8")

    monkeypatch.setattr(hf_media.urllib.request, "urlopen",
                        lambda *a, **kw: _Answer())
    assert hf_media.svgl_route("telegram", dark=True) == "telegram.svg"


def test_бренда_нет_у_источника_и_работает_их_каскад(monkeypatch):
    def boom(*a, **kw):
        raise OSError("нет сети")

    monkeypatch.setattr(hf_media.urllib.request, "urlopen", boom)
    assert hf_media.svgl_route("zzqqwoop", dark=True) is None


def test_логотип_ищется_с_именем_бренда(monkeypatch, tmp_path):
    """Каскад логотипа заводится полем `--entity`, а не общей фразой."""
    seen = {}

    def fake_run(command, **kw):
        seen["command"] = command
        return type("R", (), {"returncode": 0, "stdout": '{"ok":true,'
                              '"path":".media/images/logo_001.svg"}',
                              "stderr": ""})()

    monkeypatch.setattr(hf_media.subprocess, "run", fake_run)
    hf_media._resolve_one(tmp_path, "logo", "notion logo", "notion")
    assert "--entity" in seen["command"]
    assert seen["command"][seen["command"].index("--entity") + 1] == "notion"


def test_ролики_одной_серии_не_ставятся_в_разные_сцены(monkeypatch, tmp_path):
    """Прогон 17: один блокнот в трёх сценах — три «разных» ролика одной
    съёмочной серии Pexels (соседние номера)."""
    twin_a = {**_vcand("pexels-36633828"), "series": 36633828}
    twin_b = {**_vcand("pexels-36633851"), "series": 36633851}
    other = {**_vcand("pexels-7010308"), "series": 7010308}
    with _wire_video(monkeypatch, {"блокнот": [twin_a],
                                   "рука пишет": [twin_b, other]},
                     verdicts={"s-01": 0, "s-02": 0}) as pool:
        found = hf_media._resolve_videos(
            tmp_path, [_vreq("s-01", "блокнот"), _vreq("s-02", "рука пишет")],
            pool=pool)
    assert found["s-01"]["file"].endswith("pexels-36633828.mp4")
    assert found["s-02"]["file"].endswith("pexels-7010308.mp4")


def test_несудённая_сцена_остаётся_без_вставки(monkeypatch, tmp_path):
    """Судья пропустил сцену — берём НЕ первого из выдачи Pexels.

    Прогон 23: судья молча не ответил, сборка взяла первых кандидатов, и в
    ролик про продажи приехали игральные карты.
    """
    with _wire_video(monkeypatch, {"стол": [_vcand("первый")]},
                     verdicts={"s-02": 0}) as pool:
        found = hf_media._resolve_videos(tmp_path, [_vreq("s-01", "стол")],
                                         pool=pool)
    assert "не судили" in found["s-01"]["error"]


def test_судья_не_ответил_дважды_роняет_подбор(monkeypatch):
    """Отказ судьи — пересдача, а потом остановка, а не сборка вслепую."""
    calls = []

    class _Мёртвый:
        def run(self, prompt, cwd=None):
            calls.append(prompt)
            raise TimeoutError("не уложился")

    with pytest.raises(RuntimeError, match="судья бироллов"):
        hf_media.judge_previews(
            [{"key": "s-01", "intent": "стол", "speech": "речь",
              "previews": [["/tmp/a-0.jpg", "/tmp/a-1.jpg"]]}],
            runner=_Мёртвый())
    assert len(calls) == hf_media.JUDGE_ATTEMPTS


def test_кадры_кандидата_обложка_и_середина():
    """Второй кадр берём из их же раскадровки, без лишних запросов."""
    video = {"image": "https://p/cover.jpg",
             "video_pictures": [{"picture": f"https://p/{i}.jpg"}
                                for i in range(5)]}
    assert hf_media._preview_frames(video) == ["https://p/cover.jpg",
                                               "https://p/2.jpg"]


# ---------- окружение их CLI ----------

def test_путь_к_их_cli_дописывается_сам(tmp_path, monkeypatch):
    """`heygen` их установщик кладёт в `~/.local/bin`, а systemd даёт службе
    голый PATH без него. Мы зовём CLI по имени и ловим только ненулевой код
    возврата — отсутствие бинарника летит исключением и роняет первый же
    подбор картинки. На сервере это блокер, локально невидим."""
    import os
    from reels_factory import config

    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))

    env = config.cli_env()
    assert env["PATH"].split(os.pathsep)[0] == str(home / ".local" / "bin")
    # второй раз путь не дублируется
    monkeypatch.setenv("PATH", env["PATH"])
    assert config.cli_env()["PATH"] == env["PATH"]


def test_без_папки_путь_не_трогаем(tmp_path, monkeypatch):
    import os
    from reels_factory import config

    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    assert config.cli_env()["PATH"] == "/usr/bin"
