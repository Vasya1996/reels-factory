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


# ---------- расход судьи ----------
#
# Судья бироллов — вторая по деньгам сессия сборки: на прогоне 462a1c62 пять
# его вызовов стоили $0,79 против $0,45 у планировщика. Своя обёртка ему нужна
# ради дешёвой модели, поэтому в счёт ролика он попадает через общий кошелёк.

def _fake_судья_cli(monkeypatch, команды):
    import json
    from reels_factory import hf_agent

    def fake_run(cmd, **kw):
        команды.append([str(c) for c in cmd])

        class P:
            returncode = 0
            stdout = json.dumps({"result": json.dumps({"s-01": 0}),
                                 "total_cost_usd": 0.16,
                                 "usage": {"output_tokens": 900}})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)


def test_расход_судьи_ложится_в_кошелёк_сборки(monkeypatch, tmp_path):
    """Свою сессию судья заводит сам, а расход обязан отдать в общий кошелёк —
    иначе большая половина работы агента ролику ничего не стоит."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    команды: list[list[str]] = []
    _fake_судья_cli(monkeypatch, команды)
    кошелёк = hf_agent.AgentSpend()

    hf_media.judge_previews(
        [{"key": "s-01", "intent": "стол", "speech": "речь",
          "previews": [["/tmp/a-0.jpg", "/tmp/a-1.jpg"]]}], spend=кошелёк)

    assert [run["model"] for run in кошелёк.runs] == ["claude-haiku-4-5"]
    assert кошелёк.total_cost_usd == pytest.approx(0.16)
    # и модель с глубиной рассуждения остались судейскими, а не планировочными
    assert команды[0][команды[0].index("--model") + 1] == "claude-haiku-4-5"
    assert "--effort" not in команды[0]


def test_кошелёк_доходит_до_судьи_через_подбор(monkeypatch, tmp_path):
    """Кошелёк заводит сборка, а тратит его судья внутри подбора вставок:
    проверяем сам провод, а не только его концы."""
    from reels_factory import hf_agent

    видано = {}
    кошелёк = hf_agent.AgentSpend()

    with _wire_video(monkeypatch, {"стол": [_vcand("первый")]}) as pool:
        # _wire_video глушит судью своей заглушкой — подменяем её ловушкой,
        # которая запоминает, с чем судью позвали.
        monkeypatch.setattr(hf_media, "judge_previews",
                            lambda requests, **kw: видано.update(kw) or {"s-01": 0})
        hf_media._resolve_videos(tmp_path, [_vreq("s-01", "стол")], pool=pool,
                                 agent_spend=кошелёк)

    assert видано.get("spend") is кошелёк


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


def test_имя_превью_не_несёт_запрещённых_windows_символов(tmp_path, monkeypatch):
    """Живой прогон 17.08 на Windows: ключ сцены бывает составным
    («s-07::shot0»), а двоеточие в имени файла Windows не принимает — каждое
    превью падало с «Invalid argument», судья оставался без кадров, и ролик
    выходил вовсе без вставок. На сервере (Linux) двоеточие законно, поэтому
    дефект всплыл только локально.
    """
    from reels_factory import hf_media

    from pathlib import Path

    сохранено = []

    def fake_download(url, path):
        сохранено.append(Path(path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"jpg")
        return Path(path)

    # Ключ стока к делу не относится: тест про имя файла, а не про поиск. Без
    # подмены он проходил только там, где ключ лежит в окружении, и падал на
    # сервере.
    monkeypatch.setattr(hf_media, "_download", fake_download)
    # Сток подменён целиком: тест про имя файла превью, а не про поиск, и без
    # этой подмены он проходил только там, где в окружении лежит ключ Pexels.
    monkeypatch.setattr(hf_media, "search_pexels", lambda *a, **kw: [
        {"id": "1", "url": "https://example/1.mp4", "width": 1080,
         "height": 1920, "duration": 8.0, "preview": "https://example/p1.jpg",
         "previews": ["https://example/p1.jpg"]}])
    monkeypatch.setattr(hf_media, "judge_previews",
                        lambda requests, **kw: {r["key"]: None for r in requests})

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        hf_media._resolve_videos(
            tmp_path,
            [{"key": "s-07::shot0", "intent": "руки за ноутбуком",
              "speech": "и всё это делает программа"}],
            pool=pool)

    assert сохранено, "превью не скачивались — тест ничего не проверяет"
    for path in сохранено:
        assert ":" not in path.name, f"двоеточие в имени файла: {path.name}"


# ---------- значки ----------

def _wire_icons(monkeypatch, catalog, verdicts=None, judge=None):
    """Каталог значков без сети. `judge` — своя подмена судьи."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(hf_media, "search_assets",
                        lambda intent, **kw: catalog.get(intent, []))
    monkeypatch.setattr(hf_media, "_download", lambda url, target: target)
    monkeypatch.setattr(
        hf_media, "ingest",
        lambda public, url, **kw: {"ok": True,
                                   "path": ".media/icons/"
                                           + url.rsplit("/", 1)[-1]})
    monkeypatch.setattr(hf_media, "judge_previews",
                        judge or (lambda requests, **kw: verdicts or {}))
    return ThreadPoolExecutor(max_workers=2)


def _ireq(key, intent):
    return {"key": key, "type": "icon", "intent": intent, "speech": "реплика"}


def _icand(id_, suffix=".png"):
    return {"id": id_, "url": f"https://icons/{id_}{suffix}"}


def test_значок_отбирает_судья_а_не_первый_из_выдачи(monkeypatch, tmp_path):
    """Их провайдер значка берёт `results[0]` без всякой оценки
    (`media-use/scripts/lib/image-provider.mjs:24-42`) — то же самое «без суда
    в кадр попадает первое, что отдал сток», от которого биролл уже отучен."""
    with _wire_icons(monkeypatch,
                     {"plate": [_icand("тарелка-сверху"), _icand("сковорода")]},
                     verdicts={"s-01::icon": 1}) as pool:
        found = hf_media._resolve_icons(tmp_path, [_ireq("s-01::icon", "plate")],
                                        pool=pool)
    assert found["s-01::icon"]["file"].endswith("сковорода.png")


def test_забракованный_значок_не_ставится_вовсе(monkeypatch, tmp_path):
    with _wire_icons(monkeypatch, {"plate": [_icand("тарелка-сверху")]},
                     verdicts={"s-01::icon": None}) as pool:
        found = hf_media._resolve_icons(tmp_path, [_ireq("s-01::icon", "plate")],
                                        pool=pool)
    assert "error" in found["s-01::icon"]


def test_несудимый_значок_не_подставляется_первым(monkeypatch, tmp_path):
    """Судья пропустил сцену — это не повод брать первого из выдачи."""
    with _wire_icons(monkeypatch, {"plate": [_icand("любой")]},
                     verdicts={}) as pool:
        found = hf_media._resolve_icons(tmp_path, [_ireq("s-01::icon", "plate")],
                                        pool=pool)
    assert "error" in found["s-01::icon"]


def test_отказ_судьи_значков_не_роняет_сборку(monkeypatch, tmp_path):
    """Биролл держит кадр, и его несудимость роняет прогон. Значок только
    закрывает то, что не закрыто другим: его ошибку разберёт `settle_fillers`,
    а сцену переберёт `settle_empty_frames`."""
    def упал(requests, **kw):
        raise RuntimeError("судья значков не отработал за 2 попытки")

    with _wire_icons(monkeypatch, {"plate": [_icand("любой")]},
                     judge=упал) as pool:
        found = hf_media._resolve_icons(tmp_path, [_ireq("s-01::icon", "plate")],
                                        pool=pool)
    assert "error" in found["s-01::icon"]


def test_один_значок_не_ставится_в_две_сцены(monkeypatch, tmp_path):
    with _wire_icons(monkeypatch,
                     {"plate": [_icand("общий")], "fork": [_icand("общий")]},
                     verdicts={"s-01::icon": 0, "s-02::icon": 0}) as pool:
        found = hf_media._resolve_icons(
            tmp_path, [_ireq("s-01::icon", "plate"), _ireq("s-02::icon", "fork")],
            pool=pool)
    assert found["s-01::icon"]["file"].endswith("общий.png")
    assert "error" in found["s-02::icon"]


def test_вектор_судье_не_показывают(monkeypatch, tmp_path):
    """Судья смотрит картинки инструментом Read, а `.svg` он не откроет: такой
    кандидат до суда не доходит и первым в кадр не подставляется."""
    показано = {}

    def судья(requests, **kw):
        показано.update({r["key"]: r["previews"] for r in requests})
        return {r["key"]: 0 for r in requests}

    with _wire_icons(monkeypatch,
                     {"plate": [_icand("вектор", ".svg"), _icand("растр")]},
                     judge=судья) as pool:
        found = hf_media._resolve_icons(tmp_path, [_ireq("s-01::icon", "plate")],
                                        pool=pool)
    assert len(показано["s-01::icon"]) == 1
    assert found["s-01::icon"]["file"].endswith("растр.png")


def test_значок_идёт_своим_путём_а_не_слепым(monkeypatch, tmp_path):
    """Тип `icon` вышел из слепого ведра `resolve_all`: слепым остаётся то,
    где выбирать не из чего (знак бренда, звук)."""
    вызвано = []
    monkeypatch.setattr(hf_media, "_resolve_one",
                        lambda *a, **kw: вызвано.append(a) or {"ok": False})
    monkeypatch.setattr(hf_media.Path, "exists", lambda self: True)
    with _wire_icons(monkeypatch, {"plate": [_icand("годный")]},
                     verdicts={"s-01::icon": 0}):
        found = resolve_all(tmp_path, [_ireq("s-01::icon", "plate")])
    assert not вызвано
    assert found["s-01::icon"]["file"].endswith("годный.png")


def test_причина_судьи_попадает_в_лог_и_не_мешает_выбору(capsys):
    """Судья значков отвечает объектом: сначала что видно на значке, потом
    номер, — как в словаре жестов («`rationale` идёт перед выбором»). Прежде в
    логе оставалось только «судья забраковал все значки», и было не понять,
    дело в запросе или в выдаче каталога."""
    picks = hf_media._picks(
        {"s-01::icon": {"why": "сверху читается кольцами", "pick": 2},
         "s-02::icon": {"why": "у всех набор фигур", "pick": None}},
        subject="значков")
    assert picks == {"s-01::icon": 2, "s-02::icon": None}
    лог = capsys.readouterr().out
    assert "сверху читается кольцами" in лог
    assert "у всех набор фигур" in лог


def test_голый_номер_судьи_разбирается_по_прежнему():
    """Форма ответа у судьи бироллов своя, и машинка разбора одна на обоих."""
    assert hf_media._picks({"s-01": 1, "s-02": None},
                           subject="бироллов") == {"s-01": 1, "s-02": None}


def test_неразобранный_номер_не_считается_отказом(capsys):
    """Отказ судья пишет `null`, и по нему сцена остаётся без значка навсегда.
    Мусор вместо номера — не отказ: запись выпадает, и `_resolve_icons` назовёт
    сцену несудимой."""
    picks = hf_media._picks({"s-01::icon": {"why": "не разобрал", "pick": "да"}},
                            subject="значков")
    assert picks == {}
    assert "номер не разобрать" in capsys.readouterr().out


def test_промпт_судьи_значков_размечен_и_с_примерами():
    """Канон Anthropic: переменный вход отделён тегом от инструкции («XML tags
    help Claude parse complex prompts unambiguously»), различение показано
    примерами («Include 3–5 examples for best results»), а вместо списка
    запретов дана причина («Tell Claude what to do instead of what not to
    do»)."""
    prompt = hf_media._ICON_JUDGE_PROMPT
    assert prompt.count("<instructions>") == 1 and "</instructions>" in prompt
    assert prompt.count("<example>") >= 3
    assert "<scenes>\n{scenes}\n</scenes>" in prompt
    # причина ограничения названа там же, где само ограничение
    assert "кольца и полосы вместо предмета" in prompt
    # и переменный вход судьи бироллов размечен тем же тегом
    assert "<scenes>\n{scenes}\n</scenes>" in hf_media._JUDGE_PROMPT


def test_судья_значков_получает_реплику_сцены(monkeypatch, tmp_path):
    """Промпт обещает судье реплику диктора — значит она обязана доехать: без
    неё строка про реплику дублировала бы английский запрос."""
    показано = {}

    def судья(requests, **kw):
        показано.update({r["key"]: r.get("speech") for r in requests})
        return {r["key"]: 0 for r in requests}

    with _wire_icons(monkeypatch, {"plate": [_icand("годный")]},
                     judge=судья) as pool:
        hf_media._resolve_icons(
            tmp_path,
            [{"key": "s-01::icon", "type": "icon", "intent": "plate",
              "speech": "тарелка на столе"}], pool=pool)
    assert показано["s-01::icon"] == "тарелка на столе"
