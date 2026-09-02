"""Сборка разбита на шаги; провал гейтов запускает повтор."""
import json
from pathlib import Path

import pytest

from reels_factory.avatar_islands import avatar_budget_targets
from reels_factory.editplan import MIN_FULLSCREEN_S
from reels_factory.hf_montage_skill import seconds
from reels_factory.hf_render import STEPS, reset_step, run_step, step_done


def test_шаги_в_нужном_порядке():
    assert STEPS == ("prepare", "plan", "compose", "gates", "shots", "render",
                     "loudness")


def test_маркер_отмечает_шаг(tmp_path):
    assert step_done(tmp_path, "compose") is False
    run_step(tmp_path, "compose", lambda: None)
    assert step_done(tmp_path, "compose") is True
    reset_step(tmp_path, "compose")
    assert step_done(tmp_path, "compose") is False


def test_сделанный_шаг_не_повторяется(tmp_path):
    calls = []
    run_step(tmp_path, "render", lambda: calls.append(1))
    run_step(tmp_path, "render", lambda: calls.append(2))
    assert calls == [1]


def test_упавший_шаг_не_отмечается(tmp_path):
    with pytest.raises(RuntimeError):
        run_step(tmp_path, "check", lambda: (_ for _ in ()).throw(RuntimeError("упал")))
    assert step_done(tmp_path, "check") is False


def _fakes(monkeypatch, tmp_path, storyboards):
    from contextlib import contextmanager

    from reels_factory import hf_render

    calls = []

    def fake_cli(*args, cwd, log=None, err_log=None):
        calls.append(args)
        if args[0] == "render":
            Path(args[args.index("--output") + 1]).write_bytes(b"mp4")
        if err_log is not None:
            Path(err_log).write_text("рендер прошёл", encoding="utf-8")
        if args[0] == "check" and log is not None:
            # их `check` кода выхода не отдаёт — вердикт читается из отчёта
            Path(log).write_text('{"ok": true}', encoding="utf-8")
        if args[0] == "snapshot":
            shots = Path(cwd) / "snapshots"
            shots.mkdir(parents=True, exist_ok=True)
            (shots / "contact-sheet.jpg").write_bytes(b"jpg")
        return ""

    monkeypatch.setattr(hf_render, "_cli", fake_cli)
    monkeypatch.setattr(hf_render, "_normalize_loudness",
                        lambda src, dst: (dst.write_bytes(b"n"), dst)[1])
    monkeypatch.setattr(hf_render, "_place_clips", lambda public, *a, **k: [
        {"file": "clips/clip-00.mp4", "start": 0.0, "duration": 20.0,
         "media_start": 0.0}])
    monkeypatch.setattr(hf_render, "vendor_gsap", lambda public: public)
    monkeypatch.setattr(hf_render, "face_box_for",
                        lambda video, out, **k: {"cx": 540, "cy": 520, "h": 260})
    monkeypatch.setattr(hf_render, "inject_fonts", lambda public, **k: [])

    # Каталог и проба живой композиции требуют реестра на диске и браузера —
    # здесь проверяется поток сборки, а не они сами.
    @contextmanager
    def fake_catalog():
        yield "http://127.0.0.1:0"

    monkeypatch.setattr(hf_render, "serve_catalog", fake_catalog)
    monkeypatch.setattr(hf_render, "probe_gates",
                        lambda rdir, **k: {"D8_face": "PASS",
                                           "D14_presenter_moves": "PASS",
                                           "D15_inserts_visible": "PASS",
                                           "D17_service_text": "PASS"})
    monkeypatch.setattr(hf_render.hf_captions, "stage", lambda rdir: rdir)
    monkeypatch.setattr(hf_render, "collect_intents", lambda board: [])
    monkeypatch.setattr(hf_render, "settle_inserts",
                        lambda board, found, clips, duration, public=None: [])
    monkeypatch.setattr(hf_render, "resolve_all",
                        lambda public, requests, **kw: {})
    monkeypatch.setattr(hf_render, "rhythm_gates",
                        lambda mp4: {"D18_change_rate": "PASS",
                                     "D19_static_span": "PASS"})

    def fake_build(rdir, sdk, *, storyboard, clips, duration, words,
                   resolved=None, sfx_whoosh=None, theme=None, face=None):
        public = Path(rdir) / "public"
        (public / "media").mkdir(parents=True, exist_ok=True)
        (public / "media" / "hands.jpg").write_bytes(b"\xff\xd8\xff")
        (Path(rdir) / ".media").mkdir(exist_ok=True)
        (Path(rdir) / ".media" / "manifest.jsonl").write_text(
            '{"type":"image"}\n', encoding="utf-8")
        target = public / "index.html"
        target.write_text(
            '<html><body><img src="media/hands.jpg"></body></html>',
            encoding="utf-8")
        # настоящая сборка переписывает раскадровку округлённой, и гейты судят
        # именно её — фейк обязан делать то же самое
        (Path(rdir) / "storyboard.json").write_text(
            json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
        return target

    monkeypatch.setattr(hf_render, "build_composition", fake_build)

    @contextmanager
    def fake_sdk():
        yield None

    monkeypatch.setattr(hf_render, "sdk_session", fake_sdk)

    queue = list(storyboards)

    def fake_agent(rdir, *, runner=None):
        (Path(rdir) / "public").mkdir(parents=True, exist_ok=True)
        # Свой экземпляр на каждый вызов: настоящий агент пишет файл, и сборка
        # читает его с диска — общего объекта между попытками не бывает.
        board = json.loads(json.dumps(queue.pop(0)))
        for name in ("storyboard.json", "plan.json"):
            (Path(rdir) / name).write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", fake_agent)
    (tmp_path / "src.mp4").write_bytes(b"")
    (tmp_path / "voice.wav").write_bytes(b"")
    (tmp_path / "face.json").write_text(json.dumps({"cx": 540, "cy": 520, "h": 260}),
                                        encoding="utf-8")
    return calls


PLAN = {"windows": [], "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 20.0}}

# Десять коротких предложений: `_phrase_spans` режет по сильной пунктуации от
# трёх слов, значит каждое становится своей фразой, и агенту есть что называть.
_SENTENCES = ["Мы продаём людям.", "Мы решаем боль.", "Мы даём результат.",
              "Порядок тут решает.", "Сначала спроси кому.", "Потом спроси что.",
              "И только как.", "Всё прочее вторично.", "Сохрани это видео.",
              "Прогони свой продукт.", "Проверь свою нишу.", "Сделай это сегодня."]
TIMED = {"total": 20.0,
         "blocks": [{"role": "hook", "start": 0.0, "end": 20.0,
                     "speech": " ".join(_SENTENCES)}]}

# Слова идут ровно по сценарию — так их отдаёт синтез (alignment_to_words).
WORDS = []
for _i, _w in enumerate(" ".join(_SENTENCES).split()):
    WORDS.append({"start": round(_i * 0.6, 3), "end": round(_i * 0.6 + 0.5, 3),
                  "text": _w})


def _board(scenes, duration=20.0):
    return {"schemaVersion": 3,
            "composition": {"fps": 30, "width": 1080, "height": 1920,
                            "durationSeconds": duration, "layout": "portrait"},
            "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                           "endSec": duration,
                           "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
            "subtitles": {"enabled": True},
            "scenes": scenes}


def _series(look):
    return {"shots": [look, f"{look} крупно"], "kind": "video"}


# Сцены выстилают озвучку подряд, соседние отличаются картинкой: смену даёт
# сама граница между ними (гейт D21). Три серии бироллов по два плана стоят
# полным кадром — так аватар виден меньше потолка в 60 % (D24) — и между
# собой держат лицо (D23); сцены под серию длиннее, по две фразы.
_PLAN = [([0, 0], "punch", None),
         ([1, 2], "none", "разложить бумаги"),
         ([3, 4], "punch", None),
         ([5, 6], "none", "печатает на ноутбуке"),
         ([7, 8], "full", None),
         ([9, 10], "none", "закрывает блокнот"),
         ([11, 11], "punch", None)]
GOOD = _board([{"id": f"s-{index:02d}", "intent": "зачем", "phrases": span,
                "presenter": presenter,
                "insert": _series(look) if look else None}
               for index, (span, presenter, look) in enumerate(_PLAN)])
# Наше прежнее поле сверх схемы: соблюсти его и videoTrack.bounds разом нельзя.
BAD = _board([dict(scene, **({"contentRect": {"left": 200, "top": 400,
                                              "width": 700, "height": 300}}
                             if index == 0 else {}))
              for index, scene in enumerate(json.loads(json.dumps(GOOD["scenes"])))])


# Материал раннего шага — свой, не тот, на котором проверяется сборка.
# Причина в пороге `MIN_FULLSCREEN_S`: валидатор плана монтажа меряет его на
# окне, а окна заводятся пофразно (`_assign_window` в editplan.py), то есть
# порог достаётся КАЖДОЙ фразе сцены без ведущей. На фразах TIMED по 1,8 с
# такой сцены не построить вовсе, и любой план ронял бы заказ.
#
# Речь идёт по шесть слов на фразу (`_phrase_spans` длиннее шести не режет) с
# шагом слова 0,6 с — фраза выходит 3,6 с. Одна фраза короткая, из трёх слов:
# на ней проверяется тот самый порог. Роли идут пятью блоками, и хук тянется
# на три фразы — то есть во вторую сцену, куда D28 не смотрит.
_EARLY_SENTENCES = [
    "Мы продаём результат а не процесс.",
    "Сначала спроси кому это вообще нужно.",
    "Потом спроси что человек получит взамен.",
    "И только после этого думай как.",
    "Порядок вопросов решает исход всей работы.",
    "Прогони свой продукт по трём вопросам.",
    "Возьми лист и запиши ответы честно.",
    "Проверь нишу на десяти живых людях.",
    "Собери три довода против своей идеи.",
    "Покажи чужой результат вместо своих обещаний.",
    "Сравни две цены и объясни разницу.",
    "Считай деньги ежедневно.",
    "Дальше станет проще чем кажется сейчас.",
    "Эта привычка держит всю твою воронку.",
    "Сохрани это видео оно ещё пригодится.",
    "Подпишись если хочешь такие разборы дальше.",
]
#: Роль и её фразы: (роль, первая, за последней).
_EARLY_BLOCKS = (("hook", 0, 3), ("context", 3, 6), ("development", 6, 12),
                 ("payoff", 12, 14), ("cta", 14, 16))
_WORD_STEP, _WORD_SAID, _EARLY_TAIL = 0.6, 0.5, 0.4


def _early_material():
    """Сценарий и слова синтеза для раннего шага.

    Границы блоков считаются по той же середине паузы, по которой режет фразы
    `phrase_timeline`: разойдись они — фраза попала бы в чужой блок и получила
    бы чужую роль.
    """
    words = " ".join(_EARLY_SENTENCES).split()
    said = [{"start": round(index * _WORD_STEP, 3),
             "end": round(index * _WORD_STEP + _WORD_SAID, 3), "text": word}
            for index, word in enumerate(words)]
    counts = [len(item.split()) for item in _EARLY_SENTENCES]
    first = [sum(counts[:index]) for index in range(len(counts) + 1)]
    total = round(said[-1]["end"] + _EARLY_TAIL, 3)

    def edge(sentence: int) -> float:
        return round((said[first[sentence] - 1]["end"]
                      + said[first[sentence]]["start"]) / 2, 3)

    blocks = [{"role": role,
               "start": 0.0 if start == 0 else edge(start),
               "end": total if stop == len(counts) else edge(stop),
               "speech": " ".join(_EARLY_SENTENCES[start:stop])}
              for role, start, stop in _EARLY_BLOCKS]
    return {"total": total, "blocks": blocks}, said


EARLY_TIMED, EARLY_WORDS = _early_material()
EARLY_TOTAL = EARLY_TIMED["total"]

# План ДО заказа аватара: ведущая держит открытие, весь хук и финал, середину
# несут бироллы. Заказ выходит 29,7 с из 56,1 с — ниже потолка
# AVATAR_ON_SCREEN_MAX (60 % = 33,7 с) с учётом ручек по краям каждого куска и
# дорастания короткого куска до `min_request_seconds`. Ни один кусок без
# ведущей не идёт дольше десяти секунд подряд.
_EARLY = [([0, 1], "punch", None, True),
          ([2], "full", None, True),
          ([3, 4], "none", "разложить бумаги", False),
          # Пятая вставка — на сцене с ведущей в верхней половине кадра:
          # `D34_inserts` требует от плана из десяти сцен пять моментов под
          # вставку, и четырёх «слепых» сцен на это не хватает.
          ([5], "stack", "листает записи", True),
          ([6, 7], "none", "печатает на ноутбуке", False),
          ([8], "full", None, True),
          ([9, 10], "none", "закрывает блокнот", False),
          ([11], "full", None, True),
          ([12, 13], "none", "считает на калькуляторе", False),
          ([14, 15], "punch", None, True)]
FIT = _board([{"id": f"s-{index:02d}", "intent": "зачем", "phrases": span,
               "presenter": presenter, "avatarNeeded": needed,
               "insert": _series(look) if look else None}
              for index, (span, presenter, look, needed) in enumerate(_EARLY)],
             duration=EARLY_TOTAL)


#: Настройки клиента для заказа. Без фото-аватара заказ не строится вовсе
#: (`validate_photo_avatar_iv_config`), а гейт бюджета судит ПОСТРОЕННЫЙ заказ —
#: значит и раннему шагу настройки нужны те же, по которым пойдут деньги.
ISLAND_CONFIG = {"format": "avatar",
                 "avatar": {"heygen_asset_id": "photo-asset",
                            "engine": "avatar_iv"},
                 "avatar_islands": {"enabled": True}}


def _early_edit_plan():
    """Финальный план монтажа раннего материала — вход настоящего заказа.

    Подделывать его нельзя: заказ строится ровно из него (`order_facts` в
    hf_render.py), и словарь-заглушка обошёл бы ту самую арифметику, из-за
    расхождения с которой прогон `06eb0a8f` отдал $18 и не отдал ролика.
    """
    from reels_factory.editplan import build_edit_plan, finalize_edit_plan

    draft = build_edit_plan(EARLY_TIMED, {}, index={},
                            require_asset_files=False)
    return finalize_edit_plan(draft, EARLY_TIMED, EARLY_WORDS,
                              require_asset_files=False)


EARLY_EDIT_PLAN = _early_edit_plan()


#: План монтажа, где фразу 12 держит схема (`hyperframes`). Такие окна заводили
#: случай прогона `06eb0a8f`: отказ агента их не трогал (HeyGen там не заказан),
#: сцена без ведущей разваливалась на кусок вставки и кусок схемы, кусок вставки
#: выходил короче `MIN_FULLSCREEN_S`, и `_restore_short_faceless` возвращал ему
#: ведущую вместе с секундами в счёт. Теперь отказ накрывает и графику
#: (`apply_agent_coverage`), и на этом плане держится, что заказ больше не
#: растёт.
def _scheme_edit_plan():
    plan = json.loads(json.dumps(EARLY_EDIT_PLAN))
    for window in plan["windows"]:
        if window["id"] == "window-012":
            window["coverage"] = "hyperframes"
    for phrase in plan["phrases"]:
        if phrase["id"] == "phrase-012":
            phrase["coverage"] = "hyperframes"
    return plan


SCHEME_EDIT_PLAN = _scheme_edit_plan()

# Сцена s-07 отдана вставке целиком (фразы 11–12, вместе 5,4 с — выше пола
# D31), а фразу 12 держит схема. До правки вставке доставался кусок 1,8 с, код
# возвращал ему ведущую, и в счёт приходили секунды, которых агент не заказывал.
_RESTORED = [([0, 1], "punch", None, True),
             ([2], "full", None, True),
             ([3, 4], "none", "разложить бумаги", False),
             ([5], "stack", "листает записи", True),
             ([6, 7], "none", "печатает на ноутбуке", False),
             ([8], "full", None, True),
             ([9, 10], "stack", "считает на калькуляторе", True),
             ([11, 12], "none", "закрывает блокнот", False),
             ([13], "stack", "гасит лампу", True),
             ([14, 15], "punch", None, True)]


def _restored_board(spec):
    return _board([{"id": f"s-{index:02d}", "intent": "зачем", "phrases": span,
                    "presenter": presenter, "avatarNeeded": needed,
                    "insert": _series(look) if look else None}
                   for index, (span, presenter, look, needed)
                   in enumerate(spec)], duration=EARLY_TOTAL)


#: План прогона `06eb0a8f`: сцена s-07 отдана вставке, фразу 12 держит схема.
#: Заказ по нему 37,9 с при границе 39,3 с — и возврата больше нет.
RESTORED_OVER = _restored_board(_RESTORED)


#: План монтажа, где ОДНО окно несёт фразы 11 (1,8 с) и 12 (3,6 с) — так их и
#: склеивает черновик, когда обе несут один материал. Это единственная
#: оставшаяся причина возврата ведущей: границу сцены ставит режиссёр, окно
#: заведено по раскадровке, и одно окно достаётся двум разным решениям агента.
#: Внутри ОДНОЙ сцены разойтись кускам больше нечем — отказ накрывает и графику.
def _cut_edit_plan():
    plan = json.loads(json.dumps(EARLY_EDIT_PLAN))
    windows = plan["windows"]
    keep = next(item for item in windows if item["id"] == "window-011")
    drop = next(item for item in windows if item["id"] == "window-012")
    keep["phrase_ids"] = ["phrase-011", "phrase-012"]
    for key in ("estimated_timing", "final_timing"):
        keep[key] = {"start": keep[key]["start"], "end": drop[key]["end"],
                     "duration": round(drop[key]["end"] - keep[key]["start"], 6)}
    windows.remove(drop)
    for phrase in plan["phrases"]:
        if phrase["id"] == "phrase-012":
            phrase["window_id"] = "window-011"
    for index, window in enumerate(windows):
        window["index"] = index
    return plan


CUT_EDIT_PLAN = _cut_edit_plan()

# Сцена s-07 — одна фраза 11 (1,8 с), и граница сцены режет окно 11+12 пополам:
# кусок 1,8 с уходит во вставку, кусок фразы 12 остаётся ведущей. Возврат
# срабатывает на куске, склеить его внутри сцены не с чем.
#
# Такая сцена короче пола `MIN_FULLSCREEN_S`, и D31 её и правда заворачивает —
# в обоих планах ниже одинаково. Так и должно быть: план, который гейты
# приняли, возврата больше не заводит. Возврат остался страховкой для плана,
# который гейты завернули, а агент попытки исчерпал: `plan_before_avatar`
# доезжает до заказа и с красными гейтами, и там короткий кусок уронил бы
# сборку уже с оплаченной озвучкой.
_CUT = [([0, 1], "punch", None, True),
        ([2], "stack", "открывает ноутбук", True),
        ([3, 4], "none", "разложить бумаги", False),
        ([5], "stack", "листает записи", True),
        ([6, 7], "none", "печатает на ноутбуке", False),
        ([8], "full", None, True),
        ([9, 10], "stack", "считает на калькуляторе", True),
        ([11], "none", "закрывает блокнот", False),
        ([12, 13], "stack", "гасит лампу", True),
        ([14, 15], "punch", None, True)]

#: Возврат случился, и заказ вышел за границу: 43,3 с при границе 39,3 с.
CUT_OVER = _restored_board(_CUT)
#: Тот же возврат, но сцена s-06 тоже отдана вставке: заказ 36,1 с — внутри
#: границы. Прочие правила читают оба плана одинаково.
CUT_FIT = _restored_board(
    [(([9, 10], "none", "считает на калькуляторе", False) if index == 6
      else item) for index, item in enumerate(_CUT)])


def _needed(board, flags):
    """Копия плана с проставленным `avatarNeeded` по порядку сцен."""
    marked = json.loads(json.dumps(board))
    for scene, needed in zip(marked["scenes"], flags):
        scene["avatarNeeded"] = needed
    return marked


def _hidden(board, index, look):
    """Копия плана, где сцена `index` отдана вставке и ведущей не заказывает."""
    changed = json.loads(json.dumps(board))
    changed["scenes"][index].update({"presenter": "none", "avatarNeeded": False,
                                     "insert": _series(look)})
    return changed


# Заказ на весь ролик: 57,7 с при бюджете 33,7 с.
OVER = _needed(FIT, [True] * len(_EARLY))
# Финал отдан бироллу: лицо зрителя не провожает, последняя сцена не
# полнокадровая. Заодно это спрятанный призыв — в причине пересдачи будут оба
# гейта, и это правда о таком плане.
NO_FINALE = _hidden(FIT, -1, "гасит свет в офисе")
# Финал закрыт положением, которого нет в закрытом списке задания: кадр оно
# занимает целиком, но агенту его никто не предлагал.
OVERLAY_END = json.loads(json.dumps(FIT))
OVERLAY_END["scenes"][-1]["presenter"] = "overlay"
# Короткая фраза (1,8 с) досталась сцене без ведущей: вставке нечем закрыть
# кадр, и заказ по такому плану не состоится.
SHORT_FACELESS = _hidden(FIT, 7, "закрывает ноутбук")
# Сцена, разделявшая две сцены без ведущей, сама отдана вставке: лицо пропадает
# на пяти фразах подряд (18 с) при пределе 10 с. Ни одна фраза этого куска не
# короче пола — то есть ловит план ровно новый гейт.
LONG_BLIND = _hidden(FIT, 5, "смотрит в окно")


def _plan_fakes(monkeypatch, tmp_path, boards):
    """Обвязка раннего плана: каталог и паспорта накладок изображены, агент
    отдаёт планы из очереди. Возвращает журнал вызовов."""
    from contextlib import contextmanager

    from reels_factory import hf_render

    calls = []

    @contextmanager
    def fake_catalog():
        calls.append(("serve_catalog", None))
        yield "http://127.0.0.1:0"

    monkeypatch.setattr(hf_render, "serve_catalog", fake_catalog)
    monkeypatch.setattr(hf_render, "catalog_overlay_passports", lambda: "")

    queue = list(boards)

    def fake_agent(rdir, *, runner=None, avatar_ordered=True):
        rdir = Path(rdir)
        calls.append(("plan", (rdir / "BRIEF.md").read_text(encoding="utf-8")))
        calls.append(("avatar_ordered", avatar_ordered))
        answer = queue.pop(0)
        # Ход, закончившийся без плана, — такой же ответ агента, как и план:
        # очередь принимает исключение наравне с раскадровкой.
        if isinstance(answer, Exception):
            raise answer
        board = json.loads(json.dumps(answer))
        for name in ("storyboard.json", "plan.json"):
            (rdir / name).write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", fake_agent)
    return calls


def _fails(gates: dict) -> list[str]:
    return [f"{key}: {value}" for key, value in (gates or {}).items()
            if str(value).startswith("FAIL")]


def _причина(бриф: str) -> str:
    """Раздел пересдачи из BRIEF.md — только он говорит, чем план не прошёл.

    Искать имя гейта по всему заданию больше нельзя: имена стоят и в списке
    самопроверки, который агент читает ДО работы (`hf_brief.py`), так что
    «имя гейта есть в тексте» перестало значить «этот гейт и завернул план».
    """
    части = бриф.split("## Этот план не прошёл проверку", 1)
    assert len(части) == 2, "в задании нет раздела пересдачи"
    return части[1].split("Прочитай это первым", 1)[0]


def test_ранний_план_поднимает_каталог_и_пишет_конфиг_проекта(tmp_path,
                                                              monkeypatch):
    """Дефект 9: `plan_before_avatar` звал агента в папке без `hyperframes.json`
    и без реестра на localhost. Их же `add` в такой папке не отказывает, а сам
    заводит конфиг с публичным реестром heygen-com/hyperframes
    (hyperframes-registry/references/install-locations.md:19-31) — то есть в
    кадр поедет чужой блок, а конфиг потом молча перепишет `write_project_config`.
    """
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    assert res["scenes"], "сцены раннего плана не разложены"
    # конфиг лежит в обеих папках — как его кладёт сборка
    assert (tmp_path / "hyperframes.json").exists(), "нет конфига проекта"
    assert (tmp_path / "public" / "hyperframes.json").exists(), (
        "нет конфига проекта в public/")
    config = json.loads((tmp_path / "hyperframes.json").read_text(encoding="utf-8"))
    assert config["registry"].startswith("http://127.0.0.1")
    # реестр поднят ДО того, как агента позвали
    шаги = [name for name, _ in calls]
    assert "serve_catalog" in шаги, "каталог блоков не поднят"
    assert шаги.index("serve_catalog") < шаги.index("plan")


def test_ранний_план_кладёт_расход_в_общий_кошелёк(tmp_path, monkeypatch):
    """Дефект 10: `plan_with_agent` при `runner=None` заводит обёртку без
    кошелька, и работа планировщика (по замеру $0,45 за ролик) утекает мимо
    счёта. Кошелёк один на весь ролик: ранний план и сборка складывают в него."""
    import inspect

    from reels_factory import hf_agent, hf_render

    _plan_fakes(monkeypatch, tmp_path, [FIT])
    assert "agent_spend" in inspect.signature(
        hf_render.plan_before_avatar).parameters, (
        "ранний план не принимает общий кошелёк")

    # Настоящий вход в агента вместо заглушки: проверяется проводка от обёртки
    # до кошелька. Поддельный только сам процесс `claude -p`.
    monkeypatch.setattr(hf_render, "plan_with_agent", hf_agent.plan_with_agent)
    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")

    def fake_process(cmd, **kw):
        if kw.get("cwd"):
            (Path(kw["cwd"]) / "storyboard.json").write_text(
                json.dumps(FIT), encoding="utf-8")

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.45,
                                 "usage": {"output_tokens": 5000}})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_process)

    spend = hf_agent.AgentSpend()
    hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                 alignment_words=EARLY_WORDS,
                                 agent_spend=spend)

    assert [run["model"] for run in spend.runs] == ["claude-sonnet-5"]
    assert spend.total_cost_usd >= 0.45
    assert all(run.get("usage") for run in spend.runs)


def test_финал_без_ведущей_даёт_агенту_одну_пересдачу(tmp_path, monkeypatch):
    """Работа D: заказ аватара платный и необратимый, поэтому первую и последнюю
    сцену с ведущей во весь кадр проверяют ДО него. Промах не роняет прогон, а
    возвращается агенту причиной пересдачи — ровно одной."""
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [NO_FINALE, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "пересдачи не было"
    # Причина доехала до агента заданием, а не только в stderr. Судим по имени
    # гейта и его формулировке, а не по заголовку раздела: заголовок — дело
    # `hf_brief.py`, а вот текст причины обязан приехать целиком.
    причина = _причина(планы[1])
    assert "D28_avatar_bookends" in причина
    assert "presenter `full` или `punch`" in причина
    assert NO_FINALE["scenes"][-1]["id"] in причина
    # вторая попытка принята: сцены разложены, придирок в отчёте нет
    assert res["scenes"]
    assert _fails(res.get("gates")) == []
    assert res["board"]["scenes"][-1]["presenter"] == "punch"


def test_второй_промах_финала_попадает_в_отчёт_а_не_роняет_прогон(tmp_path,
                                                                  monkeypatch):
    """Работа D: пересдача одна. Второй промах не отклоняет сборку — он уходит
    в отчёт понятной строкой, чтобы разбор прогона показал, чего не хватило."""
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [NO_FINALE, NO_FINALE])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    assert len([1 for name, _ in calls if name == "plan"]) == 2, (
        "агента позвали больше одного раза сверх первой попытки")
    провалы = _fails(res.get("gates"))
    assert провалы, "второй промах финала не попал в отчёт"
    assert NO_FINALE["scenes"][-1]["id"] in " ".join(провалы)
    # сцены всё равно разложены: заказ аватара идёт дальше по плану агента
    assert res["scenes"]


def test_превышение_бюджета_ведущей_тоже_даёт_пересдачу(tmp_path, monkeypatch):
    """Работа D: бюджет ведущей меряется на ЗАКАЗЕ (`avatarNeeded`), а не на
    показе — клипы платные. Сейчас превышение печатается только в stderr
    (avatar_islands.py около 511), то есть агент о нём не узнаёт никогда.

    Заказ ранний шаг строит сам, из плана монтажа: с прогона `06eb0a8f` гейт
    судит построенный заказ, а не оценку по сценам.
    """
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [OVER, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS,
                                       edit_plan=EARLY_EDIT_PLAN,
                                       config=ISLAND_CONFIG)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "превышение бюджета пересдачи не вызвало"
    причина = _причина(планы[1])
    assert "D29_avatar_budget" in причина
    # Дефект 5: в причине печаталась цифра потолка (33,7 с), а задание велело
    # целиться в другую (30,9 с) и мерить сложением фраз — агент видел не то
    # число и промахивался снова. Обе цифры называются одним кодом
    # (`avatar_budget_targets`), и в пересдаче стоит именно цель.
    targets = avatar_budget_targets(EARLY_TOTAL,
                                    hf_render.islands_settings(None))
    assert seconds(targets["target_seconds"]) in причина
    assert "сложением длительностей фраз" in причина
    assert _fails(res.get("gates")) == []
    # уложившийся план принят как есть
    assert [scene.get("avatarNeeded") for scene in res["board"]["scenes"]] == [
        needed for *_, needed in _EARLY]


def test_агента_на_раннем_шаге_зовут_как_шаг_до_заказа(tmp_path, monkeypatch):
    """Пункт 5: `public/` на этом шаге пуста, и первый ход сессии говорит об
    этом сам — признак идёт тем же параметром, что и в задание."""
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [FIT])

    hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                 alignment_words=EARLY_WORDS)

    assert [flag for name, flag in calls if name == "avatar_ordered"] == [False]


def test_финал_положением_вне_списка_задания_не_проходит(tmp_path, monkeypatch):
    """Пункт 16: `overlay` кадр закрывает целиком, но закрытый список положений
    в задании (`POSITIONS` в `hf_brief.py`) его не предлагает. Гейт, который
    его принимает, мягче контракта: план прошёл бы проверку до заказа и упёрся
    бы в сборку, когда клипы уже куплены."""
    from reels_factory import hf_render

    assert "overlay" not in hf_render.BOOKEND_PRESENTER
    calls = _plan_fakes(monkeypatch, tmp_path, [OVERLAY_END, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "положение вне списка задания пересдачи не вызвало"
    причина = _причина(планы[1])
    assert "D28_avatar_bookends" in причина
    assert "overlay" in причина, "агенту не сказали, что не так с финалом"
    assert _fails(res.get("gates")) == []


def test_короткая_сцена_без_ведущей_даёт_пересдачу(tmp_path, monkeypatch):
    """Порог трёх секунд валидатор меряет на ОКНЕ (editplan.py:2544), а окна
    заводятся по одной фразе. Заказ склеивает окна одного решения агента в одно
    (`_merge_agent_windows` в `avatar_islands.py`), поэтому гейт меряет СЦЕНУ —
    сумму её фраз: то же число, что увидит валидатор. Сцена короче порога
    роняла бы сборку уже после оплаты озвучки, поэтому ловим до заказа."""
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [SHORT_FACELESS, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "короткая сцена без ведущей пересдачи не вызвала"
    причина = _причина(планы[1])
    assert "D31_faceless_scenes" in причина
    # Названы и виноватая сцена, и её собственная длина: по этому тексту агент
    # чинит план, а не гадает.
    assert SHORT_FACELESS["scenes"][7]["id"] in причина
    assert "фраза 11, вместе 1,8 с" in причина
    assert "Меряется сцена целиком" in причина
    assert _fails(res.get("gates")) == []


def _laid_out(sizes, flags, step=2.4):
    """Сцены и фразы прямо на таймлайне: `sizes` — сколько фраз в сцене,
    `flags` — решение агента. Роли hook и cta стоят по краям, как их ставит
    сценарий."""
    phrases, scenes, index, clock = [], [], 0, 0.0
    for scene_index, (size, needed) in enumerate(zip(sizes, flags)):
        start = clock
        for _ in range(size):
            role = ("hook" if index == 0
                    else "cta" if index == sum(sizes) - 1 else "development")
            phrases.append({"id": index, "role": role, "start": round(clock, 3),
                            "end": round(clock + step, 3)})
            clock, index = round(clock + step, 3), index + 1
        scenes.append({"id": f"s-{scene_index:02d}",
                       "startSec": start, "endSec": clock,
                       "presenter": "full" if needed else "none",
                       "avatarNeeded": needed})
    return scenes, phrases, clock


def test_порог_вставки_меряется_сценой_а_не_каждой_её_фразой():
    """Тот же порог с обеих сторон: две фразы по 2,4 с в одной сцене без
    ведущей дают 4,8 с — заказ склеит их в одно окно (`_merge_agent_windows` в
    `avatar_islands.py`), и вставка успевает прочитаться. Одна такая фраза
    своей сценой не дотягивает и до заказа не идёт.

    Пофразный порог заворачивал оба случая, и на быстрой речи не проходил
    вообще ни один план."""
    from reels_factory import hf_render

    settings = hf_render.islands_settings(None)

    scenes, phrases, total = _laid_out([2, 2, 2, 2], [True, False, True, True])
    gates = hf_render._early_plan_gates(scenes, total, phrases, settings)
    assert gates["D31_faceless_scenes"] == "PASS", gates["D31_faceless_scenes"]

    scenes, phrases, total = _laid_out([2, 1, 2, 2], [True, False, True, True])
    gates = hf_render._early_plan_gates(scenes, total, phrases, settings)
    assert gates["D31_faceless_scenes"].startswith("FAIL")
    assert "s-01 — фраза 2, вместе 2,4 с" in gates["D31_faceless_scenes"]


def test_фраза_роли_hook_в_средней_сцене_без_ведущей_проходит_гейты():
    """Решение Васи: правило «роли `hook` и `cta` ролик всегда говорит лицом»
    снято, остаётся только край ролика (`D28_avatar_bookends`) — открытие
    и финал. Хук тянется на три фразы
    (`_EARLY_BLOCKS`), фраза 2 — во второй, не крайней, сцене; сцена s-01
    отдана вставке (`avatarNeeded: false`), а s-00 (открытие) и s-09 (финал)
    остаются с ведущей. План обязан пройти ранние гейты и `validate_edit_plan`
    без единого упоминания роли."""
    from reels_factory import hf_render
    from reels_factory.avatar_islands import apply_agent_coverage
    from reels_factory.editplan import (
        build_edit_plan, finalize_edit_plan, validate_edit_plan,
    )
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    board = json.loads(json.dumps(FIT))
    # Фраза 2 несёт роль hook (`_EARLY_BLOCKS`) и лежит в сцене s-01 — код
    # переводит эту сцену на вставку. Соседнюю s-02 держим с ведущей, иначе
    # два отказа подряд сливаются в один промежуток дольше `MAX_FACE_ABSENCE_S`
    # (`D32_face_absence`) — это другой, не наш, гейт.
    board["scenes"][1].update({"presenter": "none", "avatarNeeded": False,
                               "insert": _series("листает ежедневник")})
    board["scenes"][2].update({"presenter": "full", "avatarNeeded": True,
                               "insert": None})

    phrases = phrase_timeline(EARLY_TIMED, EARLY_WORDS)
    scenes = lay_out_scenes(json.loads(json.dumps(board["scenes"])), phrases,
                            duration=EARLY_TOTAL)

    draft = build_edit_plan(EARLY_TIMED, {}, index={}, require_asset_files=False)
    edit_plan = finalize_edit_plan(draft, EARLY_TIMED, EARLY_WORDS,
                                   require_asset_files=False)

    facts = hf_render.order_facts(edit_plan, scenes, ISLAND_CONFIG)
    assert facts["plan"] is not None, facts.get("error")
    gates = hf_render._early_plan_gates(scenes, EARLY_TOTAL, phrases,
                                        hf_render.islands_settings(None),
                                        order=facts)
    assert _fails(gates) == [], gates
    # Гейтов ровно столько, сколько судит план сейчас — роли среди них больше
    # нет: снятое правило не оставило ни ключа, ни молчаливого PASS.
    assert set(gates) == {"D28_avatar_bookends", "D29_avatar_budget",
                          "D31_faceless_scenes", "D32_face_absence",
                          "D33_avatar_decisions", "D34_inserts",
                          "D35_frame_filled"}, gates

    out = apply_agent_coverage(edit_plan, scenes)
    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]
    hook_windows = [w for w in out["windows"] if w.get("role") == "hook"]
    assert hook_windows, "окно роли hook пропало из плана"
    assert any(w["coverage"] not in {"avatar", "mixed"} for w in hook_windows), (
        "тест бессмыслен: ни одно окно роли hook не спрятано")


def test_долгая_пропажа_лица_даёт_пересдачу(tmp_path, monkeypatch):
    """Хвост третьего круга: раннего гейта на `MAX_FACE_ABSENCE_S` не было.
    План, где сцены без ведущей идут подряд дольше предела, валидатор плана
    монтажа заворачивает («лицо отсутствует дольше 10с», editplan.py:2548-2556)
    — то есть сборка падала с уже оплаченной озвучкой, как и на дефекте 1.
    Место этой проверке там же, где остальным: до заказа."""
    from reels_factory import hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [LONG_BLIND, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "долгая пропажа лица пересдачи не вызвала"
    причина = _причина(планы[1])
    assert "D32_face_absence" in причина
    # Названы все сцены куска и его длина: агент чинит план, а не гадает, между
    # какими сценами вернуть ведущую.
    assert "идут подряд без ведущей 18 с" in причина
    for индекс in (4, 5, 6):
        assert LONG_BLIND["scenes"][индекс]["id"] in причина
    # Остальной гейт этот план принимает: фразы куска не короче пола.
    assert "D31_faceless_scenes" not in причина
    assert _fails(res.get("gates")) == []


def test_бюджет_считает_ручки_каждого_куска_заказа(tmp_path):
    """Дефект 3б: остров длиннее `max_shot_seconds` заказ режет на несколько
    кусков (`_partition_island`), и каждый кусок покупается со своей парой
    ручек. Счёт по острову целиком говорил PASS, а счёт HeyGen приходил
    больше.

    Своей арифметики у гейта больше нет вовсе: `order_facts` строит настоящий
    заказ и берёт `avatar_billed_seconds` — число, которое выставит HeyGen. Тут
    и проверяется, что берётся именно оно: сумма длительностей ЗАПРОСОВ, где
    ручки каждого шва уже учтены.
    """
    from reels_factory import hf_render
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    phrases = phrase_timeline(EARLY_TIMED, EARLY_WORDS)
    scenes = lay_out_scenes(json.loads(json.dumps(OVER["scenes"])), phrases,
                            duration=EARLY_TOTAL)
    settings = hf_render.islands_settings(None)

    факты = hf_render.order_facts(EARLY_EDIT_PLAN, scenes, ISLAND_CONFIG)
    заказ = факты["plan"]
    assert заказ is not None, факты["error"]
    assert len(заказ["islands"]) == 1, "весь ролик с ведущей — это один остров"
    assert len(заказ["shots"]) > 1, (
        f"остров {EARLY_TOTAL} с обязан разрезаться: предел куска "
        f'{settings["max_shot_seconds"]} с')

    # Ручки внутренних швов в счёте есть: крайние упираются в границы ролика и
    # не покупаются, поэтому платных ручек ровно две на каждый шов.
    швы = len(заказ["shots"]) - 1
    assert факты["billed_seconds"] == pytest.approx(
        EARLY_TOTAL + 2 * швы * settings["handle_seconds"], abs=0.001), (
        "ручки внутренних швов в бюджет не попали — гейт скажет PASS, а счёт "
        "придёт больше")
    # И это ровно то число, которым гейт судит: сумма длительностей запросов.
    assert факты["billed_seconds"] == pytest.approx(sum(
        shot["request_timing"]["duration"] for shot in заказ["shots"]),
        abs=0.001)


def test_гейты_берут_числа_из_настроек_клиента(tmp_path, monkeypatch):
    """Дефект 3в: числа заказа брались из `DEFAULTS`, а заказ идёт по профилю
    клиента. У клиента с другой ручкой задание, гейт и счёт HeyGen считались
    бы по трём разным числам."""
    from reels_factory import hf_render

    # Профиль клиента: ручка втрое длиннее умолчания и куски вдвое короче —
    # значит швов больше, и каждый докупает свою пару ручек.
    config = json.loads(json.dumps(ISLAND_CONFIG))
    config["avatar_islands"].update({"handle_seconds": 0.9,
                                     "min_request_seconds": 3.0,
                                     "target_shot_seconds": 6.0,
                                     "max_shot_seconds": 6.0})
    # План с ведущей на семи сценах из десяти: на умолчаниях заказ выходит
    # 36,9 с при границе 39,3 с и проходит, на профиле клиента — 50,7 с и не
    # проходит. Тот же план на умолчаниях брать нельзя: между ориентиром 60 %
    # и границей 70 % план годен, и `FIT` (29,7 с) не завернул бы ни один
    # профиль — тест проверял бы не ту разницу.
    rich = json.loads(json.dumps(FIT))
    rich["scenes"][2].update({"presenter": "full", "avatarNeeded": True,
                              "insert": None})
    # Оба хода одинаковые: агент промахнулся дважды, и второй промах уходит в
    # отчёт, а не роняет прогон.
    calls = _plan_fakes(monkeypatch, tmp_path, [rich, rich])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS,
                                       edit_plan=EARLY_EDIT_PLAN,
                                       config=config)

    планы = [text for name, text in calls if name == "plan"]
    # На умолчаниях этот же план проходит (см. соседние тесты) — значит и заказ
    # собран по настройкам клиента, а не по DEFAULTS.
    assert len(планы) == 2, "ручка клиента в бюджет гейта не попала"
    assert "D29_avatar_budget" in _причина(планы[1])
    # Те же числа уехали в задание: агент целится в бюджет той арифметикой,
    # которой его потом судят.
    assert "0,9 с" in планы[0]
    assert _fails(res.get("gates")), "второй промах бюджета не попал в отчёт"


def test_сцена_без_решения_агента_не_доходит_до_заказа(tmp_path, monkeypatch):
    """Дефект 3: сцену без `avatarNeeded` гейты считали заказанной, а перенос
    решения на фразы её не трогал вовсе (`apply_agent_coverage` в
    `avatar_islands.py`) — покрытие там оставалось эвристическим. Прогон это и
    показал: все гейты зелёные, а `build_avatar_render_plan` упал на «лицо
    отсутствует дольше 10.0с» уже после оплаты озвучки. Решение обязано быть у
    каждой сцены, и его отсутствие — причина пересдачи с именем сцены."""
    from reels_factory import hf_render

    молчит = json.loads(json.dumps(FIT))
    молчит["scenes"][4].pop("avatarNeeded")
    calls = _plan_fakes(monkeypatch, tmp_path, [молчит, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "сцена без решения пересдачи не вызвала"
    причина = _причина(планы[1])
    assert "D33_avatar_decisions" in причина
    assert молчит["scenes"][4]["id"] in причина
    assert _fails(res.get("gates")) == []


def _гейт_бюджета(scenes, phrases, settings, duration=EARLY_TOTAL):
    """Вердикт D29 при заказе ровно в названные секунды.

    Заказ подаём готовым словарём `order_facts`: настоящий заказ строится из
    плана монтажа, и подогнать его секунды к границе с точностью до одной
    нельзя — а проверять надо именно черту, по которой гейт делит PASS и FAIL.
    Ключ `plan` при этом непустой: пустой означает «заказ не собрался», и гейт
    тогда снимается в SKIP, а не судит.
    """
    from reels_factory import hf_render

    def гейт(заказ: float, restored=()) -> str:
        order = {"plan": {"summary": {"avatar_billed_seconds": заказ}},
                 "edit_plan": {}, "billed_seconds": заказ,
                 "restored": list(restored), "error": ""}
        return hf_render._early_plan_gates(
            scenes, duration, phrases, settings,
            order=order)["D29_avatar_budget"]

    return гейт


def _разложить(board, duration=EARLY_TOTAL, timed=None, words=None):
    """Сцены плана с проставленными секундами — так их читают гейты."""
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    phrases = phrase_timeline(timed or EARLY_TIMED, words or EARLY_WORDS)
    scenes = lay_out_scenes(json.loads(json.dumps(board["scenes"])), phrases,
                            duration=duration)
    return scenes, phrases


def test_бюджет_судит_построенный_заказ_а_не_оценку():
    """Черта бюджета — это `avatar_billed_seconds` построенного заказа против
    `hard_ceiling_seconds`, и ничего между ними не стоит.

    До прогона `06eb0a8f` (01.09.2026) гейт судил СВОЮ оценку заказа по сценам
    агента и прибавлял к ней допуск на собственную неточность. Оценка не знала
    про `_restore_short_faceless` (`avatar_islands.py`), который возвращает
    ведущую куску короче `MIN_FULLSCREEN_S`: на том прогоне она дала 29,383 с
    при настоящем заказе 36,213 с. Число, которого никто не заказывал, судить
    нельзя ни в ту, ни в другую сторону.
    """
    from reels_factory import hf_render

    scenes, phrases = _разложить(FIT)
    settings = hf_render.islands_settings(None)
    граница = avatar_budget_targets(EARLY_TOTAL,
                                    settings)["hard_ceiling_seconds"]

    гейт = _гейт_бюджета(scenes, phrases, settings)
    assert гейт(граница - 1.0) == "PASS"
    assert гейт(граница) == "PASS", "граница объявлена годной — она годна"
    assert гейт(граница + 1.0).startswith("FAIL")


def test_прогон_06eb0a8f_допуск_заворачивал_заказ_укладывающийся_в_границу():
    """Регрессия боевого прогона `06eb0a8f` (01.09.2026): $18 списаны, ролик не
    отдан.

    Числа того прогона: ролик 42,533 с, граница 29,773 с, оценка гейта
    29,383 с, настоящий заказ 36,213 с, окон с возвращённой ведущей — пять.
    Оценка укладывалась в границу, а завернул план ДОПУСК: полпроцента
    хронометража плюс два «непредсказанных шва» по паре ручек — 1,013 с,
    прибавленные к нашей же оценке. Дальше красный гейт заставил `pipeline.py`
    выбросить решение агента о покрытии, ведущую купили по старой эвристике, и
    сборка легла на `D12_faceless_cover` уже после оплаты.

    Допуск снят: прибавлять к построенному заказу нечего. План, чей ЗАКАЗ
    укладывается в границу, гейт не заворачивает.
    """
    from reels_factory import hf_render

    длина, граница, оценка, заказ = 42.533, 29.773, 29.383, 36.213
    допуск = 0.005 * длина + 2 * 2 * 0.2
    assert оценка <= граница < оценка + допуск, (
        "тест бессмыслен: на этих числах прежний допуск плана бы не завернул")

    scenes, phrases = _разложить(FIT)
    settings = hf_render.islands_settings(None)
    гейт = _гейт_бюджета(scenes, phrases, settings, duration=длина)
    assert граница == pytest.approx(
        avatar_budget_targets(длина, settings)["hard_ceiling_seconds"], abs=0.001)

    assert гейт(оценка) == "PASS", (
        "заказ внутри границы завернули — вернулся допуск на нашу неточность")
    # Настоящий заказ того прогона границу и правда перешёл, и это гейт обязан
    # сказать вслух: перебор в 6,4 с — не округление.
    assert гейт(заказ).startswith("FAIL")


def test_несобравшийся_заказ_снимает_бюджет_а_не_пропускает_его():
    """Заказ не построен — судить бюджет нечем, и вердикт обязан это сказать.

    PASS тут был бы выдуманным: он означает «ведущая в границе», а на деле
    никто не считал. Именно выдуманное число и стоило прогону `06eb0a8f` $18.
    """
    from reels_factory import hf_render

    scenes, phrases = _разложить(FIT)
    settings = hf_render.islands_settings(None)

    for заказ in (None,
                  {"plan": None, "edit_plan": {}, "billed_seconds": 0.0,
                   "restored": [], "error": "avatar islands требует "
                                            "avatar.heygen_asset_id"}):
        вердикт = hf_render._early_plan_gates(
            scenes, EARLY_TOTAL, phrases, settings,
            order=заказ)["D29_avatar_budget"]
        assert вердикт.startswith(hf_render.SKIPPED_VERDICT), вердикт
        assert not вердикт.startswith("PASS")
    assert "heygen_asset_id" in вердикт, (
        "не сказано, чем именно заказ не собрался")


def test_заказ_с_возвращённой_ведущей_судится_по_своим_секундам():
    """Тот же случай, но на настоящем заказе, а не на подставленном числе.

    Прогон `06eb0a8f`: сцену агент отдал вставке целиком, а код вернул ведущую
    её куску — окну короче `MIN_FULLSCREEN_S`, которое иначе уронило бы сборку
    после оплаты (`_restore_short_faceless`). Секунды возврата в счёт идут, и
    гейт обязан судить по ним, а не по замыслу агента.

    Обе стороны черты проверяются одним и тем же возвратом: план, чей заказ
    уложился (36,1 с при границе 39,3 с), гейт берёт; тот, чей вышел за
    границу (43,3 с), — заворачивает.

    Возврат берётся с той причины, которая решением агента не лечится вовсе, —
    с разреза окна границей сцены (`CUT_EDIT_PLAN`). Прежняя причина (фраза со
    схемой внутри отказанной сцены) кончилась: отказ агента накрывает и её,
    и держит это `test_прогон_06eb0a8f_отказ_накрывает_графику_и_заказ_не_растёт`.
    """
    from reels_factory import hf_render

    settings = hf_render.islands_settings(None)
    граница = avatar_budget_targets(EARLY_TOTAL,
                                    settings)["hard_ceiling_seconds"]

    прочие = {}
    for board, ждём in ((CUT_FIT, "PASS"), (CUT_OVER, "FAIL")):
        scenes, phrases = _разложить(board)
        факты = hf_render.order_facts(CUT_EDIT_PLAN, scenes, ISLAND_CONFIG)
        assert факты["plan"] is not None, факты["error"]
        assert факты["restored"] == ["s-07"], (
            "код ведущую не возвращал — тест проверяет не тот случай: "
            f'{факты["restored"]}')
        гейты = hf_render._early_plan_gates(scenes, EARLY_TOTAL, phrases,
                                            settings, order=факты)
        # Прочие правила читают оба плана одинаково: разводит их только заказ.
        # PASS у всех тут потребовать нельзя — сцену короче `MIN_FULLSCREEN_S`
        # D31 заворачивает, и это ровно та сцена, ради возврата на которой
        # план и построен.
        свои = {key: str(value)[:40] for key, value in гейты.items()
                if key != "D29_avatar_budget"}
        assert not прочие or прочие == свои, (
            "планы разошлись не только заказом: " + json.dumps(
                {key: (прочие.get(key), свои.get(key)) for key in свои
                 if прочие.get(key) != свои.get(key)}, ensure_ascii=False))
        прочие = свои
        вердикт = гейты["D29_avatar_budget"]
        assert вердикт.startswith(ждём), (
            f'заказ {факты["billed_seconds"]} с при границе {граница:.1f} с: '
            f"{вердикт}")
        if ждём == "PASS":
            assert факты["billed_seconds"] <= граница
        else:
            assert факты["billed_seconds"] > граница


def test_прогон_06eb0a8f_отказ_накрывает_графику_и_заказ_не_растёт():
    """Регрессия боевого прогона `06eb0a8f` (01.09.2026), причина вторая.

    Сцену s-07 агент отдал вставке целиком, но фразу 12 держала схема
    (`hyperframes`), и отказ её не трогал. Сцена разваливалась на кусок схемы и
    кусок вставки, склейка пару разных покрытий не берёт, кусок выходил короче
    `MIN_FULLSCREEN_S` — и код возвращал туда ведущую вместе с секундами в
    счёт. На том прогоне так вернулись два окна, и заказ вырос с 30,8 до 37,4 с.

    Теперь отказ агента накрывает и графику: покрытие у сцены одно, склейка
    собирает её обратно, возврата нет, и заказ по тому же плану ниже — 37,9 с
    против 39,7 с, то есть внутри границы 39,3 с.
    """
    from reels_factory import hf_render

    settings = hf_render.islands_settings(None)
    граница = avatar_budget_targets(EARLY_TOTAL,
                                    settings)["hard_ceiling_seconds"]

    scenes, phrases = _разложить(RESTORED_OVER)
    факты = hf_render.order_facts(SCHEME_EDIT_PLAN, scenes, ISLAND_CONFIG)

    assert факты["plan"] is not None, факты["error"]
    assert факты["restored"] == [], (
        "код вернул ведущую туда, где агент её не заказывал: "
        f'{факты["restored"]}')
    assert факты["billed_seconds"] < 39.7, (
        "заказ не уменьшился — фраза со схемой снова держит ведущую")
    assert факты["billed_seconds"] <= граница
    гейты = hf_render._early_plan_gates(scenes, EARLY_TOTAL, phrases,
                                        settings, order=факты)
    assert [key for key, value in гейты.items()
            if not str(value).startswith("PASS")] == [], гейты


def test_отказ_бюджета_называет_сцены_которым_ведущую_вернул_код():
    """Пересдача без имён сцен уходит в пустоту.

    Возврат ведущей делает КОД, и в счёте появляются секунды, которых агент не
    заказывал: на прогоне `06eb0a8f` так пришли пять окон. Агент видит перебор,
    смотрит в свой план — там всё как он задумал, — и вторая попытка повторяет
    первую. `agent_coverage.restored_windows` называет окна, а агент правит
    сцены, поэтому в отказе стоят имена СЦЕН.

    Причина возврата тут оставшаяся — разрез окна границей сцены
    (`CUT_EDIT_PLAN`): внутри одной сцены куски больше не расходятся.
    """
    from reels_factory import hf_render

    scenes, phrases = _разложить(CUT_OVER)
    settings = hf_render.islands_settings(None)
    факты = hf_render.order_facts(CUT_EDIT_PLAN, scenes, ISLAND_CONFIG)
    вердикт = hf_render._early_plan_gates(scenes, EARLY_TOTAL, phrases,
                                          settings,
                                          order=факты)["D29_avatar_budget"]

    assert вердикт.startswith("FAIL")
    assert "s-07" in вердикт, "сцена возврата в отказе не названа"
    assert seconds(MIN_FULLSCREEN_S) in вердикт, (
        "не сказано, короче чего кусок вернулся ведущей")
    # Названо и настоящее число заказа — то, по которому судили.
    assert seconds(факты["billed_seconds"]) in вердикт


def test_план_между_ориентиром_и_границей_годен():
    """Решение заказчика: ориентир доли ведущей остаётся 60 % хронометража, а
    заворачивает план только 70 %. Между ними план годен — пересдача стоит
    новой сессии планировщика, а лишние секунды ведущей в этой полосе стоят
    центы.

    Оба числа берутся из одного места (`avatar_budget_targets`), чтобы гейт и
    задание агенту читали одно и то же."""
    from reels_factory import hf_render
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    scenes, phrases = _разложить(FIT)
    settings = hf_render.islands_settings(None)
    цели = avatar_budget_targets(EARLY_TOTAL, settings)
    assert цели["ceiling_seconds"] == pytest.approx(
        AVATAR_ON_SCREEN_MAX * EARLY_TOTAL)
    assert цели["hard_ceiling_seconds"] == pytest.approx(
        AVATAR_ON_SCREEN_HARD_MAX * EARLY_TOTAL)

    гейт = _гейт_бюджета(scenes, phrases, settings)
    # Ровно посередине полосы: ориентир перейдён, граница нет.
    середина = (цели["ceiling_seconds"] + цели["hard_ceiling_seconds"]) / 2
    assert гейт(середина) == "PASS"
    # Выше границы — пересдача, и в ней названы оба числа: цель, которой агент
    # меряет свои сцены, и граница, выше которой план не берут.
    причина = гейт(цели["hard_ceiling_seconds"] + 5.0)
    assert причина.startswith("FAIL")
    assert seconds(цели["target_seconds"]) in причина
    assert seconds(цели["hard_ceiling_seconds"]) in причина
    # И третье: та же граница в мерке агента. Ею он сверяет план перед сдачей
    # (пункт сверки в BRIEF.md), и в причине пересдачи она названа тем же
    # числом — иначе отказ говорит с ним не тем словарём, каким его учили.
    assert seconds(цели["hard_target_seconds"]) in причина, (
        "причина не называет границу в счёте агента — сверка и отказ мерят "
        "план разными числами")


# --- быстрая речь: фразы около 2,4 с ------------------------------------


#: Четыре слова во фразе при шаге слова 0,6 с — фраза выходит 2,4 с. На таком
#: материале до склейки окон не проходил НИ ОДИН план: сцена без ведущей
#: разваливалась на окна короче `MIN_FULLSCREEN_S`.
_FAST_SENTENCES = [
    "Мы продаём результат сегодня.", "Сначала спроси кому нужно.",
    "Потом спроси что получат.", "И только после думай.",
    "Порядок решает исход работы.", "Прогони продукт по вопросам.",
    "Возьми лист запиши ответы.", "Проверь нишу на людях.",
    "Собери доводы против идеи.", "Покажи чужой результат честно.",
    "Сравни две цены спокойно.", "Считай деньги каждый день.",
    "Дальше станет заметно проще.", "Привычка держит твою воронку.",
    "Сохрани это видео сейчас.", "Подпишись на разборы дальше.",
]


def _fast_material():
    words = " ".join(_FAST_SENTENCES).split()
    said = [{"start": round(index * _WORD_STEP, 3),
             "end": round(index * _WORD_STEP + _WORD_SAID, 3), "text": word}
            for index, word in enumerate(words)]
    counts = [len(item.split()) for item in _FAST_SENTENCES]
    first = [sum(counts[:index]) for index in range(len(counts) + 1)]
    total = round(said[-1]["end"] + _EARLY_TAIL, 3)

    def edge(sentence: int) -> float:
        return round((said[first[sentence] - 1]["end"]
                      + said[first[sentence]]["start"]) / 2, 3)

    blocks = [{"role": role,
               "start": 0.0 if start == 0 else edge(start),
               "end": total if stop == len(counts) else edge(stop),
               "speech": " ".join(_FAST_SENTENCES[start:stop])}
              for role, start, stop in _EARLY_BLOCKS]
    return {"total": total, "blocks": blocks}, said


FAST_TIMED, FAST_WORDS = _fast_material()
FAST_TOTAL = FAST_TIMED["total"]
# Сцены по две фразы: одна фраза быстрой речи короче порога вставки, две —
# длиннее. Ведущая держит открытие, весь хук, середину и финал.
_FAST = [([0, 1], True), ([2, 3], True), ([4, 5], False), ([6, 7], False),
         ([8, 9], True), ([10, 11], False), ([12, 13], False), ([14, 15], True)]
FAST_BOARD = [{"id": f"s-{index:02d}", "intent": "зачем", "phrases": span,
               "presenter": "full" if needed else "none",
               "avatarNeeded": needed,
               "insert": None if needed else _series("разложить бумаги")}
              for index, (span, needed) in enumerate(_FAST)]


def test_быстрая_речь_проходит_гейты_валидатор_и_заказ():
    """Главное измерение работы: на фразах около 2,4 с план агента обязан
    доходить до заказа.

    До склейки окон (`_merge_agent_windows` в `avatar_islands.py`) сплошной
    перебор не находил ни одного проходящего плана: `editplan` заводит окно на
    фразу, и порог `MIN_FULLSCREEN_S` доставался каждой из них порознь.
    Единственным принимаемым планом оставалась ведущая на весь ролик — самый
    дорогой из возможных.
    """
    from reels_factory import hf_render
    from reels_factory.avatar_islands import (
        apply_agent_coverage, build_avatar_render_plan,
    )
    from reels_factory.editplan import (
        build_edit_plan, finalize_edit_plan, validate_edit_plan,
    )
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    phrases = phrase_timeline(FAST_TIMED, FAST_WORDS)
    длины = [round(item["end"] - item["start"], 2) for item in phrases]
    # Хвост последней фразы длиннее на паузу конца ролика — речь всё равно
    # быстрая: середина ровно 2,4 с.
    assert sorted(длины)[len(длины) // 2] == 2.4, f"речь не быстрая: {длины}"
    assert max(длины) <= 2.8, f"речь не быстрая: {длины}"

    scenes = lay_out_scenes(json.loads(json.dumps(FAST_BOARD)), phrases,
                            duration=FAST_TOTAL)

    draft = build_edit_plan(FAST_TIMED, {}, index={}, require_asset_files=False)
    edit_plan = finalize_edit_plan(draft, FAST_TIMED, FAST_WORDS,
                                   require_asset_files=False)
    assert len(edit_plan["windows"]) > len(_FAST), (
        "окна edit plan не пофразные — тест не про тот случай")

    # Гейты судим с построенным заказом: без него бюджет уходит в SKIP, и
    # «гейты пропустили план» значило бы «бюджет никто не считал».
    факты = hf_render.order_facts(edit_plan, scenes, ISLAND_CONFIG)
    assert факты["plan"] is not None, факты["error"]
    gates = hf_render._early_plan_gates(scenes, FAST_TOTAL, phrases,
                                        hf_render.islands_settings(None),
                                        order=факты)
    assert _fails(gates) == [], "гейты не пропустили план на быстрой речи"
    assert gates["D29_avatar_budget"] == "PASS", gates["D29_avatar_budget"]

    out = apply_agent_coverage(edit_plan, scenes)
    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]

    plan = build_avatar_render_plan(out, {
        "format": "avatar",
        "avatar": {"heygen_asset_id": "photo-asset", "engine": "avatar_iv"},
        "avatar_islands": {"enabled": True},
    }, master_audio_sha256="sha")
    summary = plan["summary"]
    assert plan["validation"]["all_pass"] is True
    # Ведущая заказана меньше чем на весь ролик — ради этого работа и делалась.
    assert summary["avatar_requested_seconds"] < FAST_TOTAL
    assert summary["avatar_budget"]["over_budget"] is False
    # Каждое окно без ведущей длиннее порога — то есть склейка сработала.
    for window in out["windows"]:
        if window["coverage"] in {"full_broll", "hyperframes"}:
            timing = window["final_timing"]
            assert timing["end"] - timing["start"] >= 3.0 - 0.002, window["id"]


def test_ход_без_плана_даёт_пересдачу_а_не_роняет_сборку(tmp_path, monkeypatch):
    """Дефект 4: сессия обрывается по своим причинам, и `plan_with_agent`
    бросал RuntimeError, который цикл попыток не ловил вовсе — прогон падал,
    хотя переспрос стоит одной сессии. После снятия прошлого `storyboard.json`
    случай стал вероятнее: подхватить файл прошлой попытки больше нельзя."""
    from reels_factory import hf_agent, hf_render

    пусто = hf_agent.AgentPlanMissing("агент не вернул storyboard.json")
    calls = _plan_fakes(monkeypatch, tmp_path, [пусто, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "пустой ход пересдачи не вызвал"
    # Причина уехала агенту тем же способом, что и провал гейта, и говорит,
    # чем заканчивать ход.
    assert "агент не вернул storyboard.json" in планы[1]
    assert "`storyboard.json`" in планы[1]
    assert res["scenes"] and _fails(res.get("gates")) == []


def test_два_пустых_хода_подряд_роняют_прогон(tmp_path, monkeypatch):
    """Дефект 4: пересдача одна. Второй пустой ход — уже отказ: заказывать
    ведущую не по чему, и молча собирать нечего."""
    from reels_factory import hf_agent, hf_render

    calls = _plan_fakes(monkeypatch, tmp_path, [
        hf_agent.AgentPlanMissing("в раскадровке нет ни одной сцены"),
        hf_agent.AgentPlanMissing("в раскадровке нет ни одной сцены")])

    with pytest.raises(hf_agent.AgentPlanMissing, match="ни одной сцены"):
        hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                     alignment_words=EARLY_WORDS)

    # Отказ пришёл ПОСЛЕ пересдачи, а не вместо неё.
    assert len([1 for name, _ in calls if name == "plan"]) == 2


def test_раннее_задание_остаётся_на_диске(tmp_path, monkeypatch):
    """Пункт 17: сборка переписывает и `BRIEF.md`, и свод правил версией
    «аватар уже заказан», а план сделан по другой — по той, где ведущей ещё
    нет. Разбирать прогон по переписанным файлам значит читать не то задание."""
    from reels_factory import hf_render

    _plan_fakes(monkeypatch, tmp_path, [FIT])

    hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                 alignment_words=EARLY_WORDS)

    from reels_factory.hf_montage_skill import SKILL_NAME

    оригиналы = (tmp_path / "BRIEF.md",
                 tmp_path / ".claude" / "skills" / SKILL_NAME / "SKILL.md")
    копии = (tmp_path / "BRIEF.plan.md", tmp_path / "SKILL.plan.md")
    ранние = [path.read_text(encoding="utf-8") for path in оригиналы]
    assert [path.read_text(encoding="utf-8") for path in копии] == ранние

    # Дальше идёт сборка: она пишет задание и свод правил заново, уже версией
    # «аватар заказан». Копии обязаны остаться прежними.
    hf_render.write_brief(tmp_path, scenario=TIMED, face=None, duration=20.0,
                          clips=[], phrases=[])

    поздние = [path.read_text(encoding="utf-8") for path in оригиналы]
    assert поздние != ранние, "сборка пишет ту же версию — проверять нечего"
    assert [path.read_text(encoding="utf-8") for path in копии] == ранние


def test_сборка_подхватывает_ранний_план_и_не_зовёт_агента_заново(tmp_path,
                                                                  monkeypatch):
    """Работа E: план сделан ДО заказа аватара, и сборка обязана взять его с
    диска — маркер шага `plan` и `plan.json` кладёт `plan_before_avatar`.

    Второй прогон агента здесь означал бы второй план уже после того, как клипы
    куплены по первому (дефект 12). Сторож на существующее поведение: очередь
    планов пуста, и любой вызов агента уронит прогон.
    """
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [])
    (tmp_path / "plan.json").write_text(json.dumps(GOOD), encoding="utf-8")
    (tmp_path / ".hf-plan.done").write_text("ok", encoding="utf-8")

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert Path(res["mp4"]).exists()
    assert res["gates"]["D11_schema"] == "PASS"


def test_сборка_проходит_все_шаги(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD])
    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=WORDS)

    assert (tmp_path / "BRIEF.md").exists()
    assert (tmp_path / "public" / "words.json").exists()
    assert not any(a[0] == "transcribe" for a in calls)
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)
    assert res["gates"]["D8_face"] == "PASS"
    assert res["gates"]["D0_check"] == "PASS"
    assert Path(res["mp4"]).exists()
    # каталог прописан до того, как агента позвали
    assert (tmp_path / "hyperframes.json").exists()


def test_расход_агента_доезжает_до_итога_сборки(tmp_path, monkeypatch):
    """Счётчик денег берёт работу агента из итога сборки, а сессии заводит сама
    сборка: план на Sonnet 5 и суд бироллов на Haiku 4.5. Пустой итог означает,
    что примерно доллар за ролик не попал в себестоимость вовсе."""
    from reels_factory import hf_agent, hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    # Настоящий вход в агента вместо заглушки: проверяется именно проводка от
    # обёртки до итога. Поддельный только сам процесс `claude -p`.
    monkeypatch.setattr(hf_render, "plan_with_agent", hf_agent.plan_with_agent)
    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")

    def fake_process(cmd, **kw):
        if kw.get("cwd"):
            (Path(kw["cwd"]) / "storyboard.json").write_text(
                json.dumps(GOOD), encoding="utf-8")

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.45,
                                 "usage": {"output_tokens": 5000}})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_process)

    # Судья живёт внутри подбора вставок; здесь он изображён одной сессией на
    # своей дешёвой модели — связка с настоящим подбором проверена в test_hf_media.
    def fake_resolve(public, requests, **kw):
        spend = kw.get("agent_spend")
        if spend is not None and any("speech" in r for r in requests):
            hf_agent.HeyGenAgentRunner(model="claude-haiku-4-5",
                                       spend=spend).run("суд")
        return {}

    monkeypatch.setattr(hf_render, "resolve_all", fake_resolve)
    monkeypatch.setattr(hf_render, "collect_intents",
                        lambda board: [{"key": "s-01::shot0", "type": "video",
                                        "intent": "стол", "rect": None,
                                        "required": False, "seconds": 2.0}])

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    модели = {run["model"] for run in res["agent_runs"]}
    assert модели == {"claude-sonnet-5", "claude-haiku-4-5"}
    assert res["agent_cost_usd"] >= 0.45 + 0.45
    assert all(run.get("usage") for run in res["agent_runs"])


def test_провал_гейтов_вызывает_повтор(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [BAD, GOOD])
    # как будто прошлый прогон уже дошёл до конца — маркеры render/loudness
    # стоят ДО первой попытки этого запуска, на старой (непровалившейся) раскадровке
    (tmp_path / ".hf-render.done").write_text("ok", encoding="utf-8")
    (tmp_path / ".hf-loudness.done").write_text("ok", encoding="utf-8")

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert res["gates"]["D11_schema"] == "PASS"
    assert "contentRect" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert Path(res["mp4"]).exists()
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)


def test_находки_их_проверки_отправляют_на_повтор(tmp_path, monkeypatch):
    """Текст за полями или на лице их `check` видит, а мы — нет. Значит его
    вердикт обязан доходить до агента, а не ронять сборку."""
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD, GOOD])
    real_cli = hf_render._cli
    checks = []

    def flaky_cli(*args, cwd, log=None, err_log=None):
        if args[0] == "check":
            checks.append(args)
            if len(checks) == 1:
                raise RuntimeError("hyperframes check упал (1): canvas_overflow")
        return real_cli(*args, cwd=cwd, log=log, err_log=err_log)

    monkeypatch.setattr(hf_render, "_cli", flaky_cli)

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert len(checks) == 2
    assert "canvas_overflow" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert Path(res["mp4"]).exists()
    assert any(a[0] == "render" for a in calls)


def test_их_check_судится_по_отчёту_а_не_по_коду_выхода(tmp_path, monkeypatch):
    """`hyperframes check` 0.7.84 отдаёт ноль всегда — и на предупреждении, и на
    «Not a directory». Гейт, написанный на коде выхода, не срабатывал ни разу."""
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD, GOOD])
    real_cli = hf_render._cli
    seen = []

    def failing_check(*args, cwd, log=None, err_log=None):
        if args[0] == "check":
            seen.append(args)
            Path(log).write_text(
                '{"ok": false, "strict": true, "lint": {"findings": ['
                '{"code": "composition_file_too_large", "severity": "warning",'
                ' "message": "684 lines"}]}}', encoding="utf-8")
            return ""
        return real_cli(*args, cwd=cwd, log=log, err_log=err_log)

    monkeypatch.setattr(hf_render, "_cli", failing_check)

    with pytest.raises(RuntimeError, match="composition_file_too_large"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert len(seen) == 2


def test_судья_получает_реплику_своей_сцены(tmp_path, monkeypatch):
    """Ключ запроса — `s-02::shot0`, а не id сцены: точное сравнение не
    совпадало ни с чем, и судья с прогона 24 судил по самому запросу."""
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    seen = []
    monkeypatch.setattr(hf_render, "collect_intents",
                        lambda board: [{"key": "s-01::shot0", "type": "video",
                                        "intent": "стол", "rect": None,
                                        "required": False, "seconds": 2.0}])
    # свуш идёт тем же `resolve_all` и реплики не несёт — смотрим только
    # заявки на вставки
    monkeypatch.setattr(hf_render, "resolve_all",
                        lambda public, requests, **kw: (
                            seen.extend(r["speech"] for r in requests
                                        if "speech" in r) or {}))

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert seen and seen[0].strip(), "реплика сцены до судьи не доехала"


def test_значки_подбираются_вторым_заходом_после_вставок(tmp_path, monkeypatch):
    """Значок — запас, и что он закрывает, известно только после
    `settle_inserts`. Пока запросы шли первым заходом вместе со вставками, на
    сцену со вставкой всё равно тратились поиск по каталогу, скачивание превью
    и доля платной сессии судьи, а занятый ею `id` каталога отбирался у сцены,
    которой закрыть кадр больше нечем."""
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    порядок = []
    monkeypatch.setattr(
        hf_render, "settle_inserts",
        lambda board, found, clips, duration, public=None: (
            порядок.append("вставки разобраны") or []))
    monkeypatch.setattr(
        hf_render, "icon_intents",
        lambda scenes: [{"key": "s-01::icon", "type": "icon",
                         "intent": "stopwatch", "rect": None,
                         "required": False, "seconds": 0}])
    заявки = []
    monkeypatch.setattr(
        hf_render, "resolve_all",
        lambda public, requests, **kw: (
            порядок.append([r["key"] for r in requests])
            or заявки.extend(requests) or {}))

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    заход = next(i for i, item in enumerate(порядок)
                 if isinstance(item, list) and "s-01::icon" in item)
    assert порядок.index("вставки разобраны") < заход
    # и реплика сцены доезжает до судьи так же, как у вставок: промпт обещает
    # ему реплику, а не один только английский запрос
    значок = next(r for r in заявки if r["key"] == "s-01::icon")
    assert "speech" in значок


def test_нерегистрированный_сабтаймлайн_роняет_рендер(tmp_path, monkeypatch):
    """Их предупреждение о сабтаймлайнах — это mp4 без слоя субтитров.

    Прогон 23: `sub_timeline_readiness_timeout`, код выхода ноль, зелёные
    гейты — и ролик без единого титра.
    """
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    real_cli = hf_render._cli

    def whining_cli(*args, cwd, log=None, err_log=None):
        out = real_cli(*args, cwd=cwd, log=log, err_log=err_log)
        if args[0] == "render":
            Path(err_log).write_text(
                "[FrameCapture] Sub-composition timelines not registered "
                "after 45000ms: caption-highlight. …\n"
                "[FrameCapture:sub_timeline_readiness_timeout] …",
                encoding="utf-8")
        return out

    monkeypatch.setattr(hf_render, "_cli", whining_cli)

    with pytest.raises(RuntimeError, match="caption-highlight"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert not (tmp_path / ".hf-render.done").exists()


def test_две_неудачи_подряд_роняют_сборку(tmp_path, monkeypatch):
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [BAD, BAD])
    with pytest.raises(RuntimeError, match="схемой не предусмотрено"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)


def test_окно_с_материалом_снимает_сайт_или_маршрут(tmp_path, monkeypatch):
    """prepare вызывает capture_site/screen_route для окон с полем material
    и кладёт результат в public/media — агенту искать материал не надо."""
    from reels_factory import capture_site, hf_render, screen_route

    calls = _fakes(monkeypatch, tmp_path, [GOOD])

    def fake_cached_capture(url, cache_dir):
        shots_dir = Path(cache_dir) / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        shot = shots_dir / "scroll-000.png"
        shot.write_bytes(b"png")
        return {"dir": str(shots_dir), "screenshots": [str(shot)], "page": ""}

    def fake_record_route(steps, out_mp4, **kw):
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"mp4")
        return out_mp4

    monkeypatch.setattr(capture_site, "cached_capture", fake_cached_capture)
    monkeypatch.setattr(screen_route, "record_route", fake_record_route)

    plan = {
        "windows": [
            {"id": "window-000", "visual_intent": "Показать интерфейс",
             "material": {"kind": "site", "url": "https://elevenlabs.io"}},
            {"id": "window-001", "visual_intent": None,
             "material": {"kind": "route",
                          "steps": [{"type": "goto", "url": "https://www.google.com"}]}},
        ],
        "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0},
    }

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=WORDS)

    media = json.loads((tmp_path / "media.json").read_text(encoding="utf-8"))
    by_window = {item["window_id"]: item for item in media}
    assert (tmp_path / "public" / by_window["window-000"]["file"]).exists()
    assert (tmp_path / "public" / by_window["window-001"]["file"]).exists()
    assert by_window["window-000"]["what"] == "Показать интерфейс"
    assert by_window["window-001"]["what"] == "запись маршрута"


def test_повторный_prepare_не_снимает_материал_заново(tmp_path, monkeypatch):
    """Маркер шага prepare делает capture/record одноразовыми: перезапуск
    сборки читает media.json, а не снимает сайт заново."""
    from reels_factory import capture_site, hf_render, screen_route

    _fakes(monkeypatch, tmp_path, [GOOD, GOOD])
    capture_calls = []
    monkeypatch.setattr(capture_site, "cached_capture",
                        lambda url, cache_dir: capture_calls.append(url) or {
                            "screenshots": []})
    monkeypatch.setattr(screen_route, "record_route",
                        lambda steps, out_mp4, **kw: capture_calls.append("route") or Path(out_mp4))

    plan = {
        "windows": [{"id": "window-000", "visual_intent": "Показать сайт",
                     "material": {"kind": "site", "url": "https://elevenlabs.io"}}],
        "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0},
    }

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert len(capture_calls) == 1

    # маркер prepare остался — второй прогон не должен снова звать capture
    hf_render.reset_step(tmp_path, "compose")
    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert len(capture_calls) == 1


def test_нехватку_вставок_ловит_ранний_гейт_а_не_сборка(monkeypatch):
    """Живой прогон 17.08: план прошёл все шесть ранних гейтов, а сборка
    упала на `check_inserts` — «вставок в плане 3, а нужно хотя бы 4».

    После работы 9 это падение приходится на момент, когда озвучка оплачена, а
    ведущая уже заказана: требование числа вставок обязано жить среди ранних
    гейтов и возвращать агенту пересдачу, а не ронять сборку.
    """
    from reels_factory import hf_render
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    phrases = phrase_timeline(EARLY_TIMED, EARLY_WORDS)
    сцены = lay_out_scenes(json.loads(json.dumps(FIT["scenes"])), phrases,
                           duration=EARLY_TOTAL)
    for scene in сцены:
        scene.pop("insert", None)

    гейты = hf_render._early_plan_gates(
        сцены, EARLY_TOTAL, phrases, hf_render.islands_settings(None))

    assert "D34_inserts" in гейты, "требование вставок не проверяется до заказа"
    assert str(гейты["D34_inserts"]).startswith("FAIL")
    assert "вставк" in str(гейты["D34_inserts"])


def _ранние(scenes):
    """Ранние гейты по этим сценам, разложенным на озвучку раннего материала."""
    from reels_factory import hf_render
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    phrases = phrase_timeline(EARLY_TIMED, EARLY_WORDS)
    разложены = lay_out_scenes(json.loads(json.dumps(scenes)), phrases,
                               duration=EARLY_TOTAL)
    return hf_render._early_plan_gates(разложены, EARLY_TOTAL, phrases,
                                       hf_render.islands_settings(None))


def test_пустой_кадр_ловит_ранний_гейт_а_не_гейт_после_рендеров():
    """Боевой прогон лёг на `D20_frame_filled: FAIL: s-06: ведущая 'pip-tl'
    без вставки не закрывает кадр`. Судит D20 уже собранный кадр, то есть
    после оплаченных рендеров HeyGen: прогон стоил $11,86 и ролика не отдал.

    Уголок ведущей и вставку выбирает агент, и до заказа это ещё его решение —
    значит место проверке среди ранних гейтов.
    """
    сцены = json.loads(json.dumps(FIT["scenes"]))
    сцены[5]["presenter"] = "pip-tl"
    сцены[5]["insert"] = None

    гейты = _ранние(сцены)

    assert "D35_frame_filled" in гейты, "пустой кадр не проверяется до заказа"
    assert str(гейты["D35_frame_filled"]).startswith("FAIL")
    assert сцены[5]["id"] in гейты["D35_frame_filled"], (
        "гейт не назвал сцену — агенту нечего чинить")
    assert "pip-tl" in гейты["D35_frame_filled"]


def test_схема_закрывает_кадр_для_раннего_гейта_наравне_со_вставкой():
    """Уголок ведущей под схемой — законная раскладка: схема стоит в верхней
    трети и кадр держит она. Судит это `schema_scene`, и ранний гейт спрашивает
    ровно его — своей копии правила у него нет.
    """
    сцены = json.loads(json.dumps(FIT["scenes"]))
    сцены[5]["presenter"] = "pip-br"
    сцены[5]["insert"] = None
    сцены[5]["schema"] = {"form": "steps", "why": "порядок",
                          "nodes": ["кто", "что", "как"]}

    assert _ранние(сцены)["D35_frame_filled"] == "PASS"


def test_пустой_кадр_возвращает_агенту_пересдачу_до_заказа(tmp_path,
                                                           monkeypatch):
    """Провал ранних гейтов — это причина пересдачи, а не отчёт: агента
    спрашивают заново, и ведущую заказывают уже по исправленному плану. Здесь
    проверяется, что новый гейт попадает в этот же круг, — иначе он повторил бы
    D20 и опоздал бы ровно так же."""
    from reels_factory import hf_render

    дыра = json.loads(json.dumps(FIT))
    дыра["scenes"][5]["presenter"] = "pip-tl"
    дыра["scenes"][5]["insert"] = None
    calls = _plan_fakes(monkeypatch, tmp_path, [дыра, FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    планы = [text for name, text in calls if name == "plan"]
    assert len(планы) == 2, "пустой кадр пересдачи не вызвал"
    причина = _причина(планы[1])
    assert "D35_frame_filled" in причина
    assert дыра["scenes"][5]["id"] in причина
    assert _fails(res.get("gates")) == []


def test_дыру_в_кадре_чинит_код_когда_попытки_агента_кончились(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Ранний FAIL прогон не останавливает: после двух попыток план ложится на
    диск как есть, и `pipeline.py:550-556` идёт заказывать ведущую по нему же.
    Покрытие там пересчитает код, а `presenter` и `insert` — нет: дыра доедет
    до оплаченного заказа и упадёт на `D20_frame_filled` уже после списания.

    Поэтому последнее слово о положении ведущей остаётся за кодом, и берёт он
    его у `positions_for` — не выдумывая своего.
    """
    from reels_factory import hf_render
    from reels_factory.hf_montage import positions_for

    дыра = json.loads(json.dumps(FIT))
    дыра["scenes"][5]["presenter"] = "pip-tl"
    дыра["scenes"][5]["insert"] = None
    # Оба хода агента — с той же дырой: попытки кончились, чинить некому.
    _plan_fakes(monkeypatch, tmp_path, [дыра, json.loads(json.dumps(дыра))])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    сцена = res["scenes"][5]
    assert сцена["id"] == дыра["scenes"][5]["id"]
    assert сцена["presenter"] in positions_for(сцена), (
        "код поставил положение мимо списка, согласованного с кадром")
    assert res["gates"]["D35_frame_filled"] == "PASS", (
        "вердикт остался прежним — в отчёт уехал не тот план, что поедет "
        "в заказ")
    # По снимку заказывают ведущую и раскладывают её на возобновлённом
    # прогоне: дыра, оставшаяся там, стоила бы второго заказа.
    снимок = json.loads((tmp_path / hf_render.EARLY_PLAN_FILE)
                        .read_text(encoding="utf-8"))
    assert снимок["scenes"][5]["presenter"] == сцена["presenter"]
    # Вставку и схему решает агент — их код не трогает.
    assert снимок["scenes"][5]["insert"] is None
    строки = capsys.readouterr().out.splitlines()
    правка = [line for line in строки if "положение ведущей поправлено" in line]
    assert правка, "код поправил чужое решение молча"
    assert сцена["id"] in правка[0] and "pip-tl" in правка[0]
    # Бот берёт последнюю строку stdout, начинающуюся с `{`, за свой ответ
    # (bot.py:1417-1426) — наша строка такой быть не должна.
    assert not any(line.startswith("{") for line in правка)


def test_зелёный_ранний_гейт_код_не_трогает(tmp_path, monkeypatch, capsys):
    """Починка — это последнее слово после исчерпанных попыток, а не правка
    каждого плана: план без дыры обязан доехать до заказа ровно таким, каким
    его написал агент."""
    from reels_factory import hf_render

    _plan_fakes(monkeypatch, tmp_path, [FIT])

    res = hf_render.plan_before_avatar(tmp_path, EARLY_TIMED,
                                       alignment_words=EARLY_WORDS)

    положения = [scene["presenter"] for scene in res["scenes"]]
    assert положения == [scene["presenter"] for scene in FIT["scenes"]]
    assert "положение ведущей поправлено" not in capsys.readouterr().out


def test_сцена_без_заказа_ведущей_закрывается_фоном_а_не_ведущей(tmp_path):
    """`avatarNeeded: false` — это дыра аватара, прочитанная до заказа
    (hf_montage.py:179-185): клипа HeyGen на этих секундах не будет, и `full`
    на такой сцене — обещание кадра, которого никто не снимет. На дыре
    `refill_scene` ставит `none`, и `fills_frame` такую сцену принимает
    (hf_layout.py:135) — тем же отвечает и починка.
    """
    from reels_factory import hf_render
    from reels_factory.hf_gates import frame_filled_problems
    from reels_factory.hf_phrases import lay_out_scenes, phrase_timeline

    board = json.loads(json.dumps(FIT))
    board["scenes"][6].update({"presenter": "pip-tl", "insert": None})
    assert board["scenes"][6]["avatarNeeded"] is False
    phrases = phrase_timeline(EARLY_TIMED, EARLY_WORDS)
    сцены = lay_out_scenes(json.loads(json.dumps(board["scenes"])), phrases,
                           duration=EARLY_TOTAL)

    правки = hf_render._fill_frame_holes(tmp_path, board, сцены)

    assert сцены[6]["presenter"] == "none"
    assert правки and сцены[6]["id"] in правки[0]
    assert frame_filled_problems(сцены) == []
    # Правка ушла и в план на диске — по нему заказывают ведущую.
    assert board["scenes"][6]["presenter"] == "none"
    записан = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert записан["scenes"][6]["presenter"] == "none"


def test_причина_ненайденной_вставки_попадает_в_лог(capsys):
    """`resolve_all` пишет на каждый ненайденный запрос свою причину в поле
    `error` (hf_media.py:874-889), и не читал их никто: вызывающие спрашивают
    только `file`. Из-за этого упавший прогон, где из десяти запросов файлы
    получились у трёх, разбирать было нечем.

    Строка не смеет начинаться с `{`: бот берёт из stdout движка последнюю
    строку, начинающуюся с `{`, и читает её как ответ (`bot.py:1417-1426`).
    """
    from reels_factory import hf_render

    hf_render._report_resolve(
        {"s-02::shot0": {"file": "media/a.mp4"},
         "s-02::shot1": {"error": "Pexels не дал кандидатов: «стол»"},
         "s-06::shot0": {"error": "судья забраковал всех кандидатов: «офис»"}},
        "вставка")

    напечатано = capsys.readouterr().out
    assert "s-02::shot1" in напечатано and "Pexels не дал кандидатов" in напечатано
    assert "s-06::shot0" in напечатано and "судья забраковал" in напечатано
    assert "файлы у 1 из 3" in напечатано, "счёта найденного в логе нет"
    assert "s-02::shot0" not in напечатано, "найденный файл попал в отчёт о потерях"
    assert not any(line.startswith("{") for line in напечатано.splitlines()), (
        "строка, начинающаяся с `{`, уедет боту вместо ответа движка")


def test_средство_которого_не_будет_снимается_до_разбора_пустых_сцен(
        tmp_path, monkeypatch):
    """Значок без файла и плашку с непригодным блоком сборка снимала сама —
    то есть ПОСЛЕ прохода, который отдаёт соседке сцену с пустым кадром
    (`settle_empty_frames` внутри `dedupe_neighbours`). Сцена, стоявшая на
    одном значке, оставалась после этого фоном с титром, и починить её коду
    было уже нечем. Теперь снимает `settle_fillers`, и порядок обязан
    держаться: сначала снять, потом разбирать."""
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    order = []
    fillers, dedupe = hf_render.settle_fillers, hf_render.dedupe_neighbours
    monkeypatch.setattr(hf_render, "settle_fillers",
                        lambda *a, **k: (order.append("снять"),
                                         fillers(*a, **k))[1])
    monkeypatch.setattr(hf_render, "dedupe_neighbours",
                        lambda *a, **k: (order.append("разобрать"),
                                         dedupe(*a, **k))[1])
    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert "снять" in order
    assert order[order.index("снять"):] == ["снять", "разобрать"]


def test_запасную_схему_меряют_до_разбора_пустых_сцен(tmp_path, monkeypatch):
    """Запасную схему назначает `settle_inserts` — уже после первого прохода по
    схемам, — и её пол секунд мерила одна сборка. Схема снималась там, где
    чинить кадр нечем: сцена на дыре без аватара оставалась фоном с титром, и
    D25 с D26 валили сборку за то, чего агент не делал. Проход обязан стоять
    между снятием средств и разбором пустых сцен."""
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [GOOD])
    order = []
    fillers = hf_render.settle_fillers
    schemas, dedupe = hf_render.settle_schemas, hf_render.dedupe_neighbours
    monkeypatch.setattr(hf_render, "settle_fillers",
                        lambda *a, **k: (order.append("снять"),
                                         fillers(*a, **k))[1])
    monkeypatch.setattr(hf_render, "settle_schemas",
                        lambda *a, **k: (order.append("схемы"),
                                         schemas(*a, **k))[1])
    monkeypatch.setattr(hf_render, "dedupe_neighbours",
                        lambda *a, **k: (order.append("разобрать"),
                                         dedupe(*a, **k))[1])
    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert "снять" in order
    assert order[order.index("снять"):] == ["снять", "схемы", "разобрать"]


# --- пересборка монтажа на уже оплаченной папке ------------------------------

def test_сброс_монтажных_маркеров_щадит_оплаченное(tmp_path):
    """Провал проверок качества чинится пересборкой монтажа, а не новым
    роликом. Снимать надо ровно монтажные шаги: prepare держит снятые сайты и
    подобранные материалы, plan-early — тот план, ПО КОТОРОМУ УЖЕ КУПЛЕНА
    ведущая у HeyGen. Сняв его, второй прогон спросил бы агента заново, и
    заказанные клипы перестали бы соответствовать плану — то есть человек
    заплатил бы за ведущую второй раз."""
    from reels_factory.hf_render import (
        EARLY_PLAN_STEP, reset_montage_steps, step_done,
    )

    монтажные = ("compose", "gates", "shots", "render", "loudness")
    for шаг in ("prepare", "plan", EARLY_PLAN_STEP, *монтажные):
        run_step(tmp_path, шаг, lambda: None)

    reset_montage_steps(tmp_path)

    for шаг in монтажные:
        assert step_done(tmp_path, шаг) is False, шаг
    assert step_done(tmp_path, "prepare") is True
    assert step_done(tmp_path, "plan") is True
    assert step_done(tmp_path, EARLY_PLAN_STEP) is True


def test_сброс_монтажных_маркеров_переживает_папку_без_них(tmp_path):
    """Сборка могла упасть до первого маркера — снимать тогда нечего, и
    падать на отсутствующем файле функция не имеет права: её зовут перед
    возвратом job в очередь, и её исключение оставило бы человека без
    продолжения вовсе."""
    from reels_factory.hf_render import reset_montage_steps

    reset_montage_steps(tmp_path)

    assert step_done(tmp_path, "compose") is False


def test_пересборка_после_провала_проверок_несёт_причину_в_задание(
        tmp_path, monkeypatch):
    """Д6. Пересборка кормит композитора тем же заданием, которое только что
    не прошло проверки.

    Причина провала уезжает в `BRIEF.md` только внутри одного прогона — в цикле
    попыток. Между прогонами она не переживает ничего: на продолжении шаг
    `prepare` пропущен (его маркер стоит), задание остаётся прежним, а маркер
    `plan` цел — агента не зовут вовсе и в кадр едет тот же план. Человек
    платит за прогон агента и рендер, чтобы получить ровно тот же ролик и тот
    же отказ.

    Причина последнего провала обязана сохраниться вместе со сборкой (папка
    job — единственное, что переживает прогон) и попасть в задание следующего.
    """
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [])
    планы = []

    def агент(rdir, *, runner=None):
        rdir = Path(rdir)
        планы.append((rdir / "BRIEF.md").read_text(encoding="utf-8"))
        board = json.loads(json.dumps(GOOD))
        for name in ("storyboard.json", "plan.json"):
            (rdir / name).write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", агент)

    def собрать():
        return hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    # Прогон 1: ролик собрался, но ритм не прошёл — ровно тот случай, из
    # которого бот делает `qa_failed` и предлагает перезапуск.
    monkeypatch.setattr(hf_render, "rhythm_gates", lambda mp4: {
        "D18_change_rate": "FAIL: картинка меняется реже раза в 2,5 секунды",
        "D19_static_span": "PASS"})
    первый = собрать()
    assert _fails(первый["gates"]), "первый прогон обязан не пройти проверки"

    # Продолжение: бот снимает монтажные маркеры и зовёт сборку на той же
    # папке. Оплаченное (`prepare`, снятые клипы) остаётся на месте.
    hf_render.reset_montage_steps(tmp_path)
    monkeypatch.setattr(hf_render, "rhythm_gates", lambda mp4: {
        "D18_change_rate": "PASS", "D19_static_span": "PASS"})
    второй = собрать()

    assert _fails(второй["gates"]) == []
    assert len(планы) == 2, (
        "на пересборке композитора не спросили заново — в кадр поехал тот же "
        "план, что проверки уже завернули")
    assert "меняется реже" in _причина(планы[1]), (
        "композитор не узнал, чем не прошёл прошлый план")


def test_отказ_гейтов_раскадровки_оставляет_причину_в_папке(
        tmp_path, monkeypatch):
    """Круг пересдачи по D21, D24 и D25 не сходился. Эти гейты валят сборку
    ИСКЛЮЧЕНИЕМ, `pipeline` возвращает `fail("assemble", …)` и причину никуда
    не пишет, а продолжение снимает монтажные маркеры, оставляя `plan` целым.
    Без записи в папке следующий прогон читает `plan.json`, пересобирает тот
    самый план, который проверки уже завернули, и получает тот же отказ —
    заплатив за суд бироллов и подбор медиа. Снять `plan` может только запись
    причины (`assemble_hyperframes` около 1176).
    """
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [])

    def агент(rdir, *, runner=None):
        rdir = Path(rdir)
        board = json.loads(json.dumps(GOOD))
        for name in ("storyboard.json", "plan.json"):
            (rdir / name).write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", агент)
    monkeypatch.setattr(hf_render, "check_storyboard", lambda board, **k: {
        "D25_empty_frame": "FAIL: s-03: ведущей нет, вставка не встала"})

    with pytest.raises(RuntimeError, match="сборка не прошла проверки"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    причина = hf_render.last_retry_reason(tmp_path)
    assert причина and "D25_empty_frame" in причина, (
        "причина отказа не пережила прогон — продолжение пересоберёт тот же "
        "завёрнутый план")


def test_отказ_замороженного_плана_остаётся_в_отчёте_но_не_валит_ролик():
    """Ранние гейты судят план, который ещё можно переписать. После заказа
    ведущей план заморожен, и тот же отказ поправить нечем: `qa_pass` уходил
    в False на каждой пересборке навсегда.

    Вердикт из отчёта не выкидываем — промах плана должен быть виден, — но
    приставку меняем: качество ролика решают гейты того, что ещё меняется.
    """
    from reels_factory.hf_render import frozen_plan_gates

    вердикты = frozen_plan_gates({
        "D29_avatar_budget": "PASS",
        "D34_inserts": "FAIL: вставок в плане 4, а нужно хотя бы 5"})

    assert вердикты["D29_avatar_budget"] == "PASS", "зелёный вердикт тронут"
    assert not вердикты["D34_inserts"].startswith("FAIL"), (
        "отказ по замороженному плану валит ролик, а поправить его нечем")
    assert "вставок в плане 4" in вердикты["D34_inserts"], (
        "промах раннего плана пропал из отчёта")


def test_имена_гейтов_спрашивают_у_кода_а_не_у_списка():
    """Список имён рядом с проверкой протухал бы ровно так же, как причина в
    папке задания: снятый гейт правился бы вторым местом.

    Проверяем на снятом `D26_flash` (64ad5ae): в исходниках он остался —
    комментарием в `hf_compose.py` и строкой докстроки в `hf_zoom.py`, — а
    выставить его код уже не умеет.
    """
    from reels_factory.hf_render import known_gate_names

    имена = known_gate_names()

    assert "D26_flash" not in имена, (
        "снятый гейт считается живым — упоминание в тексте принято за код")
    for живой in ("D34_inserts", "D18_change_rate", "D15_inserts_visible",
                  "D25_empty_frame", "D26_frame_content", "D8_face"):
        assert живой in имена, f"живой гейт {живой} не найден в коде"


def test_протухшая_причина_пересдачи_не_идёт_в_работу(tmp_path, capsys):
    """Причина живёт в папке задания, а код тем временем едет.

    Боевой случай: в папке лежал `D26_flash: FAIL: вспышка не видна…`, гейт
    сняли выкаткой (64ad5ae), а прогон честно снял маркер `plan`, переписал
    BRIEF.md разделом пересдачи и заново позвал агента чинить несуществующую
    проверку — $3.48. У живого пользователя на кнопке «продолжить» вышло бы
    то же самое.
    """
    from reels_factory import hf_render

    hf_render.save_retry_reason(
        tmp_path, "D26_flash: FAIL: вспышка не видна на 3,2 с")

    assert hf_render.last_retry_reason(tmp_path) is None, (
        "протухшая причина принята к работе — агента зовут чинить гейт, "
        "которого нет")
    assert "D26_flash" in capsys.readouterr().out, (
        "причину погасили молча — разобрать прогон будет нечем")


def test_живая_часть_причины_переживает_протухшую(tmp_path):
    """Гасим ровно протухшие куски. Живой отказ терять нельзя: без него
    продолжение пересоберёт тот же ролик за те же деньги.

    Вердикт внутри куска сам склеен через «; » (перечисление виноватых сцен),
    поэтому режется причина по имени гейта, а не простым split.
    """
    from reels_factory import hf_render

    hf_render.save_retry_reason(tmp_path, "; ".join((
        "D26_flash: FAIL: вспышка не видна",
        "D25_empty_frame: FAIL: пустой кадр: s-03; s-04",
    )))

    причина = hf_render.last_retry_reason(tmp_path)

    assert причина == "D25_empty_frame: FAIL: пустой кадр: s-03; s-04", причина


def test_причина_не_про_гейты_остаётся_как_есть(tmp_path):
    """Проверять свежесть тут нечем: имён гейтов в такой причине нет вовсе, а
    молча терять её нельзя — следующий прогон получил бы то же задание."""
    from reels_factory import hf_render

    hf_render.save_retry_reason(tmp_path, "план не лёг на озвучку — фраза 7")

    assert hf_render.last_retry_reason(tmp_path) == (
        "план не лёг на озвучку — фраза 7")


def test_протухшая_причина_не_гоняет_агента_на_продолжении(
        tmp_path, monkeypatch):
    """То же самое целиком: сборка на папке с протухшей причиной обязана
    оставить маркер `plan` и не звать агента вовсе.

    Обратный случай — свежая причина зовёт агента заново — держит
    `test_продолжение_на_островах_спрашивает_агента_по_купленным_клипам`.
    """
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [])
    (tmp_path / "plan.json").write_text(json.dumps(GOOD), encoding="utf-8")
    (tmp_path / ".hf-plan.done").write_text("ok", encoding="utf-8")
    hf_render.save_retry_reason(
        tmp_path, "D26_flash: FAIL: вспышка не видна на 3,2 с")

    звали = []
    monkeypatch.setattr(hf_render, "plan_with_agent",
                        lambda rdir, **kw: звали.append(rdir))

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert звали == [], (
        "агента позвали чинить снятый гейт — прогон стоит денег, а чинить "
        "нечего")
    assert "## Этот план не прошёл проверку" not in (
        tmp_path / "BRIEF.md").read_text(encoding="utf-8"), (
        "в задание уехал раздел пересдачи по гейту, которого нет")


#: Ставки счёта — только чтобы работа моделей вообще получила цену.
RATES_СЧЁТА_HF = {
    "heygen_usd_per_second": 0.05,
    "heygen_twin_usd_per_second": 0.0667,
    "elevenlabs_usd_per_1k_chars": 0.10,
    "chars_per_second": 14.0,
    "claude_flat_usd_per_reel": 0.05,
}


def _записи_трат_hf(ledger, job_id: str) -> dict:
    """Сколько строк в журнале трат у этой сборки, по подрядчикам."""
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT provider, COUNT(*) AS n FROM spend_log"
            " WHERE job_id = ? GROUP BY provider",
            (job_id,),
        ).fetchall()
    return {row["provider"]: int(row["n"]) for row in rows}


def test_продолжение_на_островах_спрашивает_агента_по_купленным_клипам(
        tmp_path, monkeypatch):
    """Д2. На островном пути продолжение после провала проверок — холостой
    прогон за деньги.

    Маркер `plan-early` цел (по тому плану куплена ведущая), поэтому сборка
    агента не зовёт вовсе: план тот же, значит и провал тот же. А всё, что
    вокруг плана, гоняется заново — в том числе суд бироллов моделью, который
    платный. Человек жмёт «Перезапустить сборку», ждёт прогон, платит за него
    и получает ровно тот же отказ.

    Чинится это не снятием маркера: сняв его, второй план разошёлся бы с уже
    купленными клипами. Агента надо спросить заново по УЖЕ КУПЛЕННЫМ клипам —
    задание в режиме «аватар заказан» (там ему называют, где ведущей нет) — и
    назвать причину прошлого провала. Сам маркер `plan-early` при этом
    остаётся: он про то, чем оплачена ведущая, а не про монтаж.
    """
    from reels_factory import hf_render
    from reels_factory.billing import JobMeter, LedgerStore
    from reels_factory.hf_agent import AgentSpend

    _fakes(monkeypatch, tmp_path, [])
    # Ранний план (работа 9): агент назвал сцены, ведущая куплена ровно по ним.
    (tmp_path / "plan.json").write_text(json.dumps(GOOD), encoding="utf-8")
    (tmp_path / ".hf-plan.done").write_text("ok", encoding="utf-8")
    (tmp_path / f".hf-{hf_render.EARLY_PLAN_STEP}.done").write_text(
        "ok", encoding="utf-8")

    задания = []

    def агент(rdir, *, runner=None):
        rdir = Path(rdir)
        задания.append((rdir / "BRIEF.md").read_text(encoding="utf-8"))
        кошелёк = getattr(runner, "spend", None)
        if кошелёк is not None:
            кошелёк.add({"model": "sonnet"}, 0.45)
        board = json.loads(json.dumps(GOOD))
        for name in ("storyboard.json", "plan.json"):
            (rdir / name).write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", агент)

    def суд_бироллов(public, requests, **kw):
        """Подбор вставок судит модель — платный шаг на каждом прогоне."""
        кошелёк = kw.get("agent_spend")
        if кошелёк is not None:
            кошелёк.add({"model": "haiku"}, 0.12)
        return {}

    monkeypatch.setattr(hf_render, "resolve_all", суд_бироллов)

    ledger = LedgerStore(tmp_path / "billing.sqlite3")
    ledger.credit(7, 100_000_000, purchase_id="p1", amount_minor=10_000,
                  currency="usd")

    def собрать():
        """Прогон сборки со своим кошельком — как в pipeline.run_make."""
        кошелёк = AgentSpend()
        meter = JobMeter(ledger, chat_id=7, job_id="job-острова",
                         rates=RATES_СЧЁТА_HF, markup=1.0)
        try:
            return hf_render.assemble_hyperframes(
                tmp_path, TIMED, edit_plan=PLAN,
                avatar_mp4s=[tmp_path / "src.mp4"],
                master_audio=tmp_path / "voice.wav", alignment_words=WORDS,
                agent_spend=кошелёк)
        finally:
            # Ровно то, что делает pipeline.py в finally: работа агента
            # списывается независимо от того, чем прогон кончился.
            meter.claude_agent(кошелёк.runs, кошелёк.total_cost_usd)

    # Прогон 1: ролик собрался, но ритм не прошёл — тот случай, из которого
    # бот делает qa_failed и предлагает перезапуск.
    monkeypatch.setattr(hf_render, "rhythm_gates", lambda mp4: {
        "D18_change_rate": "FAIL: картинка меняется реже раза в 2,5 секунды",
        "D19_static_span": "PASS"})
    первый = собрать()
    assert _fails(первый["gates"]), "первый прогон обязан не пройти проверки"
    assert задания == [], (
        "сборка спросила агента поверх раннего плана — ведущая куплена по "
        "нему, и второй план оставил бы оплаченные секунды без кадра")
    трата_первого = _записи_трат_hf(ledger, "job-острова")

    # Продолжение: бот снимает монтажные маркеры и зовёт сборку на той же
    # папке. Оплаченное (prepare, plan-early, купленные клипы) остаётся.
    hf_render.reset_montage_steps(tmp_path)
    monkeypatch.setattr(hf_render, "rhythm_gates", lambda mp4: {
        "D18_change_rate": "PASS", "D19_static_span": "PASS"})
    второй = собрать()

    assert _fails(второй["gates"]) == []
    assert трата_первого.get("claude", 0) > 0, "первый прогон обязан платить"
    assert _записи_трат_hf(ledger, "job-острова").get("claude", 0) > (
        трата_первого.get("claude", 0)), (
        "продолжение — это ещё одно списание за работу моделей: суд бироллов "
        "гоняется заново на каждом прогоне")
    assert len(задания) == 1, (
        "на продолжении композитора не спросили — в кадр поехал тот же план, "
        "который проверки уже завернули, а деньги за прогон списаны")
    assert "## Где ведущей нет" in задания[0], (
        "задание пересдачи написано в режиме «аватар ещё не заказан» — агент "
        "решал бы, где ведущая нужна, поверх уже купленных клипов")
    assert "меняется реже" in _причина(задания[0]), (
        "композитор не узнал, чем не прошёл прошлый прогон")
    assert hf_render.step_done(tmp_path, hf_render.EARLY_PLAN_STEP) is True, (
        "снят маркер раннего плана — по нему куплена ведущая")


def test_сдвиг_точки_замера_не_обещает_закрыть_наложение_текстов():
    """Докстрока `_scene_midpoints` обосновывала сдвиг на `start + 3.6` тем,
    что их конвейер по той же причине не бьёт по границам твинов. Для
    `content_overlap` это прямо неверно: его пересчитывают отдельным проходом
    по плотной сетке 8 кадров в секунду на всю длительность, независимо от
    `--at` (`collectMotionOverlapSamples`, checkPipeline.ts:437-465 на пине
    0.7.84). Сдвиг закрывает только находки редкой сетки, и докстрока обязана
    называть именно их — иначе следующий читатель будет чинить наложение
    выборкой."""
    from reels_factory.hf_render import _scene_midpoints

    doc = _scene_midpoints.__doc__ or ""
    for code in ("text_box_overflow", "clipped_text", "text_occluded"):
        assert code in doc, f"докстрока не называет {code}"
    assert "content_overlap" in doc and "НЕ закрывает" in doc, (
        "докстрока снова обещает закрыть content_overlap сдвигом выборки")

    board = {"scenes": [
        {"id": "s-01", "startSec": 0.0, "endSec": 6.0},
        {"id": "s-02", "startSec": 6.0, "endSec": 14.0,
         "overlay": {"block": "lt-clean-bar"}}]}
    assert _scene_midpoints(board) == [3.0, 9.6]


#: Потолок доставки на время теста. Настоящие 50 МБ пришлось бы писать на диск,
#: а вся арифметика ужатия — это отношение веса к длительности.
ПОТОЛОК_В_ТЕСТЕ = 6 * 1024 * 1024


def _громкость_без_ffmpeg(monkeypatch, tmp_path, вес_первого: int):
    """Оба прохода `_normalize_loudness` без ffmpeg: команды пишем в список, а
    файл — заданного веса."""
    from reels_factory import hf_render

    команды = []

    def fake_run(cmd, **kw):
        команды.append([str(part) for part in cmd])
        out = Path(cmd[-1])
        out.write_bytes(b"x" * (вес_первого if len(команды) == 1 else 10))
        return None

    monkeypatch.setattr(hf_render.subprocess, "run", fake_run)
    monkeypatch.setattr(hf_render, "media_dur", lambda src: 90.0)
    monkeypatch.setattr(hf_render, "MAX_DELIVERY_BYTES", ПОТОЛОК_В_ТЕСТЕ)
    src = tmp_path / "reel.raw.mp4"
    src.write_bytes(b"raw")
    return hf_render._normalize_loudness(src, tmp_path / "reel.mp4"), команды


def test_ролик_тяжелее_потолка_доставки_ужимается_сборкой(monkeypatch, tmp_path):
    """P6-02: картинка шла `-c:v copy`, и вес ролика не ограничивался ничем —
    на замеренных 6,08 Мбит/с 50 МБ набегают к 69-й секунде. Дальше полностью
    оплаченный ролик становился невыдаваемым: Telegram его не берёт, а
    пересборка веса не меняет и кнопки продолжения на этой стадии нет."""
    из_потолка = ПОТОЛОК_В_ТЕСТЕ

    mp4, команды = _громкость_без_ffmpeg(monkeypatch, tmp_path, из_потолка + 1)

    assert len(команды) == 2, "тяжёлый ролик уехал зрителю как есть"
    ужатие = команды[1]
    assert ужатие[ужатие.index("-c:v") + 1] != "copy", (
        "картинку снова скопировали — вес остался прежним")
    битрейт = int(ужатие[ужатие.index("-b:v") + 1])
    assert битрейт * 90.0 / 8 <= из_потолка, (
        "целевой битрейт не влезает в потолок доставки")
    assert mp4.stat().st_size <= из_потолка
    # Звук уже выровнен первым проходом — второй раз его не жмут.
    assert ужатие[ужатие.index("-c:a") + 1] == "copy"


def test_обычный_ролик_второй_раз_не_кодируется(monkeypatch, tmp_path):
    """Второй проход — только для тех роликов, что в потолок не влезли:
    лишнее пережатие стоило бы качества каждому ролику."""
    _, команды = _громкость_без_ffmpeg(monkeypatch, tmp_path, ПОТОЛОК_В_ТЕСТЕ)

    assert len(команды) == 1
