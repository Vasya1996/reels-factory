"""Оркестрация сборки рилса (этап make): голос -> (split: аватар) -> видеоряд
-> сборка -> QA. Сценарий берётся из workdir/scenario.json (после валидации
пользователем на этапе script).

run_make() гонит стадии подряд; при исключении на любой стадии останавливается и
возвращает {"ok": False, "workdir", "mp4": None, "qa_pass": False, "stage",
"error"}. DI на внешние ресурсы (synth/avatar/assemble/covered_block) —
тестируемо без сети/ffmpeg. verify_reel не параметр (детерминированная QA-логика).

{"ok": True, "qa_pass": False, ...} — тоже штатный исход, не отказ: файл
собрался и прошёл до конца, но какой-то гейт красный. С работы 05 такой ролик
`bot.py` доставляет как обычный, а изъян остаётся в `gates`/result_json.

При ``RF_MASTER_AUDIO_ENABLED=1`` (либо ``master_audio.enabled: true``) весь
утверждённый сценарий озвучивается одним ElevenLabs request. По alignment из
master WAV режутся технические block WAV только для переходного HeyGen-пути;
финальный render проигрывает исключительно master WAV.

До TTS/HeyGen строится единственный versioned ``edit_plan.json``. После master
alignment в нём уточняются только тайминги и явные safety-fallbacks. Только
validator-approved full B-roll window может пометить блок ``avatar_required:
false`` и заменить невидимый HeyGen дешёвым локальным placeholder. Сборщик
HyperFrames получает тот же документ: по нему пишется задание агенту и по нему
же проверяются гейты вставок.

Новый сборщик работает только с мастер-звуком и только с форматами ``split`` и
``avatar``; неподдержанный конфиг отбивается до первого платного вызова.

На пути avatar islands ведущую заказывают ПОСЛЕ плана агента: сперва
``hf_render.plan_before_avatar`` (там же проверка плана и пересдача), он же
переносит решение ``avatarNeeded`` на фразы и строит по нему заказ
(``hf_render.order_facts`` поверх ``avatar_islands``), и только по
размеченному плану режутся острова.
Сессии агента считаются одним кошельком на прогон, и он списывается в
``finally``: деньги за них потрачены независимо от того, чем прогон кончился.

Заказ ведущей замораживается папкой задания. Лежат в ней годные
``avatar_render_plan.json`` с ``avatar_render_manifest.json`` и снятые клипы —
пересборка берёт их как есть: ни один из двух LLM-проходов (визуальный
директор и жесты) не зовётся, границы шотов не двигаются, HeyGen не вызывается.
Условия годности перечислены в ``avatar_islands.load_frozen_avatar_order``,
байты мастер-звука сверяются здесь же, когда дорожка построена или загружена.
"""
import hashlib
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT, edit_settings
from reels_factory.billing import billable_seconds
from reels_factory.avatar import (
    HeyGenClient, avatar_cache_key, cached_generate, render_covered_block,
)
from reels_factory.tts import synth_voice as _synth_voice
from reels_factory.master_audio import (
    build_master_audio as _build_master_audio,
    load_approved_master_audio,
    master_audio_enabled,
)
from reels_factory.compose import apply_caption_fixes, build_caption_fixes
# Рендер-слой: HyperFrames (единственный рендерер). Контракт результата тот же
# ({"mp4","timed_scenario","words_fixed"}) плюс "gates" от гейтов раскадровки.
from reels_factory.hf_render import (
    assemble_hyperframes as _assemble,
    frozen_plan_gates as _frozen_plan_gates,
    plan_before_avatar as _plan_before_avatar,
    save_retry_reason as _save_retry_reason,
    step_done as _step_done,
    reset_step as _reset_step,
    run_step as _run_step,
    EARLY_PLAN_STEP,
)
# Кошелёк сессий агента: один на прогон, общий для раннего плана и сборки.
from reels_factory.hf_agent import AgentSpend
from reels_factory.edit import jump_cut_fragments as _jump_cut_fragments
from reels_factory.editplan import (
    build_edit_plan as _build_edit_plan,
    covered_block_indexes,
    enrich_performance_with_llm,
    enrich_visuals_with_llm,
    ensure_assetless_visual_coverage,
    finalize_edit_plan as _finalize_edit_plan,
    performance_response_schema,
    save_edit_plan,
)
from reels_factory.avatar_islands import (
    avatar_islands_enabled,
    build_avatar_render_plan as _build_avatar_render_plan,
    load_frozen_avatar_order,
    render_avatar_islands as _render_avatar_islands,
    save_avatar_render_plan,
    validate_photo_avatar_iv_config,
)
from reels_factory.llm import ClaudeCliRunner
from reels_factory.verify import verify_reel

AVATAR_CACHE_DIRNAME = "avatar_cache"

#: Маркер заказа ведущей на пути «без монтажа». Кэша островов там нет — весь
#: ролик снимается одним вызовом HeyGen, — и второй прогон на той же папке без
#: маркера значит второй заказ за те же деньги. В MONTAGE_STEPS его нет
#: намеренно: пересборка монтажа снятый клип не отменяет.
PLAIN_AVATAR_STEP = "plain-avatar"


def _log(stage: str) -> None:
    print(f"[make] {stage}", file=sys.stderr)


def _fixes_hypothesis(config: dict) -> dict:
    product = config.get("product") or {}
    return {
        "theme": config.get("theme"),
        "theme_spoken": config.get("theme_spoken"),
        "theme_captions": config.get("theme_captions"),
        "brand_captions": product.get("brand_captions"),
    }


def _run_plain_avatar(config: dict, wd, scenario: dict, voice_id,
                      avatar_client, meter, *, master_audio_fn=None):
    """Ролик без монтажа: единая утверждённая дорожка -> один вызов HeyGen.

    Возвращает путь к mp4 (звук уже вшит HeyGen). Монтажный слой не строится
    и не вызывается вовсе. Master audio обязателен: без него нет единой дорожки
    на весь ролик, а поблочная озвучка — это уже монтажный путь.
    """
    avatar_cfg = config.get("avatar") or {}
    if avatar_client is None:
        avatar_client = HeyGenClient(
            avatar_id=avatar_cfg.get("heygen_asset_id"),
            look_id=avatar_cfg.get("heygen_look_id"),
            motion_prompt=avatar_cfg.get("motion_prompt"),
            expressiveness=avatar_cfg.get("expressiveness"),
            engine=avatar_cfg.get("engine"),
            resolution=avatar_cfg.get("resolution"),
        )
    if not master_audio_enabled(config):
        raise RuntimeError(
            "режим без монтажа требует master_audio.enabled=true: нужна одна "
            "утверждённая дорожка на весь ролик"
        )
    out_mp4 = wd / "reel.mp4"
    # Продолжение той же папки не заказывает ведущую заново. Минута HeyGen
    # стоит около трёх долларов, а кнопка продолжения обещает ровно обратное —
    # «платить за них второй раз не придётся». Маркера мало: он мог остаться от
    # прогона, чей файл потом удалили, — поэтому смотрим и на сам клип.
    if _step_done(wd, PLAIN_AVATAR_STEP):
        if out_mp4.is_file():
            return out_mp4
        # Маркер без файла: заказ прошёл, а клип с папки пропал. Продолжать
        # нечем, поэтому маркер снимаем и заказываем заново.
        _reset_step(wd, PLAIN_AVATAR_STEP)

    approval_path = wd / "audio.approved.json"
    review_required = bool(
        ((config.get("master_audio") or {}).get("review_required", False))
    )
    if approval_path.exists():
        master = load_approved_master_audio(scenario, config, wd)
    elif review_required:
        raise RuntimeError("render заблокирован: master audio ещё не утверждено")
    else:
        master = (master_audio_fn or _build_master_audio)(
            scenario, config, wd, voice_id=voice_id,
            meter=(meter.elevenlabs if meter is not None else None),
        )
    def order():
        mp4 = avatar_client.generate(master.wav, out_mp4)
        if meter is not None:
            meter.heygen(
                billable_seconds(mp4),
                twin=bool(getattr(avatar_client, "look_id", None)),
            )
        return mp4

    # Списание идёт внутри шага: маркер ставится только после ответа HeyGen, и
    # заказ, оборвавшийся на середине, повторится на продолжении.
    return _run_step(wd, PLAIN_AVATAR_STEP, order)


def run_make(config: dict, workdir,
             scenario: dict | None = None,
             avatar_client=None, synth_fn=None, assemble_fn=None,
             covered_block_fn=None, jump_cut_fn=None, precut_fn=None,
             master_audio_fn=None, edit_plan_fn=None,
             finalize_edit_plan_fn=None, visual_runner=None,
             performance_runner=None,
             avatar_plan_fn=None, avatar_render_fn=None, meter=None) -> dict:
    fmt = config.get("format", "split")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    synth_fn = synth_fn or _synth_voice
    assemble_fn = assemble_fn or _assemble
    covered_block_fn = covered_block_fn or render_covered_block
    jump_cut_fn = jump_cut_fn or _jump_cut_fragments
    edit_cfg = edit_settings(config)
    use_master_audio = master_audio_enabled(config)
    use_avatar_islands = False

    def fail(stage, e):
        return {"ok": False, "workdir": str(wd), "mp4": None, "qa_pass": False,
                "stage": stage, "error": str(e)[:500]}

    # Отказ от неподдержанного конфига — до единственного ElevenLabs запроса и
    # до HeyGen: деньги не должны списываться ради ошибки, которую видно сразу.
    if fmt == "fullscreen":
        return fail("config", RuntimeError(
            "формат fullscreen не поддержан новым сборщиком"))
    if not use_master_audio:
        return fail("config", RuntimeError(
            "новый сборщик работает только с мастер-звуком; включи master_audio"))

    if scenario is None:
        try:
            scenario = json.loads((wd / "scenario.json").read_text(encoding="utf-8"))
        except Exception as e:
            return fail("scenario", e)

    voice_id = config.get("voice_id")
    config_language = str(config.get("language") or "").strip().lower()
    voice_language = str(config.get("voice_language") or "").strip().lower()
    voices = config.get("voices")
    scenario_language = str(scenario.get("language") or "").strip().lower()
    tts_language = str(
        ((config.get("tts") or {}).get("language_code") or config_language)
    ).strip().lower()
    if scenario_language and scenario_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"язык сценария {scenario_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if tts_language and tts_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"TTS language_code {tts_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if voice_language and voice_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"язык активного голоса {voice_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if voices is not None and (
        not isinstance(voices, dict)
        or str(voices.get(config_language) or "").strip()
        != str(voice_id or "").strip()
    ):
        return fail(
            "language",
            RuntimeError(
                f"в профиле нет подходящего голоса для языка "
                f"{config_language!r}"
            ),
        )
    avatar_cfg = config.get("avatar") or {}

    # Режим без монтажа: одна утверждённая дорожка -> один проход HeyGen. Ни
    # edit_plan, ни B-roll, ни субтитров, ни Revideo, ни QA-геймов — отдаём
    # сырой talking-head mp4 (звук уже вшит HeyGen). Ветка ранняя, чтобы не
    # строить и не финализировать монтажный план впустую.
    if config.get("montage") is False:
        _log("plain_avatar")
        try:
            out_mp4 = _run_plain_avatar(
                config, wd, scenario, voice_id, avatar_client, meter,
                master_audio_fn=master_audio_fn,
            )
        except Exception as e:
            return fail("plain_avatar", e)
        return {
            "ok": True,
            "workdir": str(wd),
            # str, а не Path: результат уходит через json.dumps в _cmd_make
            "mp4": str(out_mp4),
            # Ролик отдаём — он оплачен и собран, — но приёмку он не проходил:
            # композиции здесь нет, субтитров нет, звук идёт прямо из HeyGen без
            # нашей нормализации, и ни один гейт D1..D7 не считался. Прежде
            # отчёт нёс один `qa_pass: True`, и непроверенный ролик выглядел в
            # нём ровно как прошедший все проверки. Читатель отчёта различает
            # эти случаи по `qa_checked`.
            "qa_pass": True,
            "qa_checked": False,
            "gates": None,
            "avatar_summary": None,
            "avatar_render_manifest": None,
            "montage": False,
            "stage": None,
            "error": None,
        }

    caption_fixes = build_caption_fixes(_fixes_hypothesis(config))

    # Один canonical edit plan строится до любых TTS/HeyGen вызовов. Старый
    # injected precut_fn допускается только как источник legacy hints для
    # совместимости тестов/CLI; решения всё равно нормализует editplan.py.
    _log("plan")
    # Заказ ведущей, уже лежащий в папке задания. Не None — пересборка идёт по
    # нему: ни границы шотов, ни жесты не пересчитываются, HeyGen не зовётся.
    frozen_order = None

    def построить_план():
        """Свежий edit plan: разметка и два платных LLM-прохода."""
        legacy_plan = None
        if precut_fn is not None and fmt == "avatar":
            legacy_plan = precut_fn(scenario, config)
        plan = (edit_plan_fn or _build_edit_plan)(
            scenario,
            config,
            legacy_broll_plan=legacy_plan,
        )
        visual_cfg = (
            (((config.get("edit_plan") or {}).get("visual_director") or {})
             .get("llm") or {})
        )
        if visual_cfg.get("enabled"):
            runner = visual_runner or ClaudeCliRunner(
                timeout_s=int(visual_cfg.get("timeout_s") or 600)
            )
            plan = enrich_visuals_with_llm(plan, runner)
        # Даже при выключенном/недоступном Visual LLM длинный участок без
        # подходящего B-roll не должен оставаться одной talking head сценой.
        # Функция идемпотентна и заполняет только свободные avatar-only окна.
        plan = ensure_assetless_visual_coverage(plan)
        performance_cfg = (
            ((config.get("edit_plan") or {}).get("performance_llm") or {})
        )
        if performance_cfg.get("enabled"):
            runner = performance_runner or ClaudeCliRunner(
                timeout_s=int(performance_cfg.get("timeout_s") or 600),
                # Жест выбирается из enum-а, а не сочиняется: форму ответа
                # держит сам CLI (`--json-schema`).
                json_schema=performance_response_schema(),
            )
            plan = enrich_performance_with_llm(plan, runner)
        save_edit_plan(plan, wd)
        for line in plan.get("log") or []:
            print(f"[plan] {line}", file=sys.stderr)
        return plan

    try:
        use_avatar_islands = avatar_islands_enabled(config)
        if use_avatar_islands:
            if fmt not in ("split", "avatar"):
                raise RuntimeError(
                    "avatar islands поддерживает только format=split|avatar"
                )
            if not use_master_audio:
                raise RuntimeError(
                    "avatar islands требует master_audio.enabled=true"
                )
            validate_photo_avatar_iv_config(config)
            # Ведущая, снятая прошлым прогоном этой папки, покупается один
            # раз. Оба LLM-прохода выбирают заново и границы шотов, и жесты, а
            # от них зависит и нарезка мастер-звука, и ключ кэша
            # (`avatar.avatar_cache_key`): пересчитав план, мы бы промахнулись
            # мимо снятых клипов и заплатили второй раз. Поэтому при годном
            # заказе план берётся с диска целиком — вместе с решениями обоих
            # проходов, других их читателей нет. Мастер-звук сверяется ниже,
            # когда он построен или загружен.
            frozen_order = load_frozen_avatar_order(wd, config)
        if frozen_order is not None:
            edit_plan = frozen_order["edit_plan"]
        else:
            edit_plan = построить_план()
    except Exception as e:
        return fail("plan", e)

    if fmt in ("split", "avatar") and avatar_client is None:
        avatar_client = HeyGenClient(
            avatar_id=avatar_cfg.get("heygen_asset_id"),
            look_id=avatar_cfg.get("heygen_look_id"),
            motion_prompt=avatar_cfg.get("motion_prompt"),
            expressiveness=avatar_cfg.get("expressiveness"),
            engine=avatar_cfg.get("engine"),
            resolution=avatar_cfg.get("resolution"),
        )

    # Только validator-approved full cover может отключить HeyGen. Решение
    # адресуется block index, а не ролью: повторяющиеся роли не конфликтуют.
    covered_blocks = covered_block_indexes(edit_plan) if fmt == "avatar" else set()

    # Кошелёк сессий агента на этот прогон: и ранний план (работа 9), и сборка
    # складывают расход в него. Списывается он в finally, потому что деньги за
    # сессии потрачены независимо от того, чем прогон кончился: раньше
    # meter.claude_agent стоял после успешной сборки, и упавшая теряла работу
    # планировщика целиком. У бота та же задача решена так же (_charge_claude).
    # Кошелёк заводится на каждый прогон свой: сборка возобновляемая, второй
    # запуск на той же папке агента не зовёт, и общий кошелёк списал бы с
    # человека работу первого прогона второй раз.
    agent_spend = AgentSpend()
    try:
        _log("voice")
        try:
            avatar_mp4s, voice_wavs = [], []
            master = None
            avatar_render_plan = None
            avatar_render_manifest = None
            # Отчёт проверки плана ДО заказа аватара (работа D). Пустой на всех
            # путях, где раннего плана нет вовсе.
            early_gates = {}
            cache_dir = WORK_ROOT / AVATAR_CACHE_DIRNAME
            if use_master_audio:
                approval_path = wd / "audio.approved.json"
                review_required = bool(
                    ((config.get("master_audio") or {}).get("review_required", False))
                )
                if approval_path.exists():
                    master = load_approved_master_audio(scenario, config, wd)
                elif review_required:
                    raise RuntimeError(
                        "render заблокирован: master audio ещё не утверждено"
                    )
                else:
                    master_audio_fn = master_audio_fn or _build_master_audio
                    master = master_audio_fn(
                        scenario, config, wd, voice_id=voice_id,
                        meter=(meter.elevenlabs if meter is not None else None),
                    )
                block_wavs = list(master.block_wavs)
                if (
                    not use_avatar_islands
                    and len(block_wavs) != len(scenario["blocks"])
                ):
                    raise RuntimeError(
                        f"master audio blocks {len(block_wavs)} != "
                        f"scenario blocks {len(scenario['blocks'])}"
                    )
            else:
                block_wavs = []
                for i, b in enumerate(scenario["blocks"]):
                    text = b.get("speech")
                    if not text:
                        raise RuntimeError(f"блок {i} ({b.get('role')}): пустой speech")
                    wav = wd / f"voice_{i}.wav"
                    synth_fn(
                        text, wav, voice_id=voice_id,
                        meter=(meter.elevenlabs if meter is not None else None),
                    )
                    block_wavs.append(wav)

            # Последнее условие заморозки: те ли байты мастер-звука. Раньше их
            # не проверить — дорожка либо синтезируется, либо грузится именно
            # здесь. Разошлись — заказ не годен, и план считается честно, со
            # всеми проходами: клипы сняты под другой звук.
            if frozen_order is not None:
                master_sha256 = hashlib.sha256(
                    Path(master.wav).read_bytes()).hexdigest()
                заказан_под = frozen_order["plan"].get("master_audio_sha256")
                if заказан_под != master_sha256:
                    print(
                        "[make] заказ ведущей пересобирается: мастер-звук "
                        "сменился после заказа",
                        file=sys.stderr,
                    )
                    frozen_order = None
                    edit_plan = построить_план()

            if master is not None:
                if frozen_order is None:
                    finalize_edit_plan_fn = (
                        finalize_edit_plan_fn or _finalize_edit_plan
                    )
                    edit_plan = finalize_edit_plan_fn(
                        edit_plan,
                        master.timed_scenario,
                        list(master.words),
                    )
                    save_edit_plan(edit_plan, wd)
                # Замороженный план уже финализирован и уже размечен решением
                # агента — тем самым, по которому куплены клипы. Второй проход
                # `finalize_edit_plan` тут только рисковал бы сдвинуть окна
                # мимо оплаченного заказа.
                covered_blocks = (
                    covered_block_indexes(edit_plan) if fmt == "avatar" else set()
                )

            if use_avatar_islands and frozen_order is not None:
                avatar_render_plan = frozen_order["plan"]
                avatar_render_manifest = frozen_order["manifest"]
                avatar_mp4s = list(frozen_order["clips"])
                # Гейты раннего плана — часть отчёта по сборке, и на
                # пересборке они те же: план заморожен заказом. Считаются они
                # из `plan.early.json` без единой сессии агента, но только при
                # маркере шага; без него `plan_before_avatar` пошёл бы
                # спрашивать агента заново, а это деньги.
                #
                # Судить качество ролика они здесь уже не вправе: план куплен
                # вместе с ведущей, и его отказ не поправить ничем, кроме
                # второго заказа. `_frozen_plan_gates` оставляет вердикт в
                # отчёте, но снимает с него право валить `qa_pass` — иначе
                # кнопка «продолжить» упирается в вечный отказ (подробности и
                # боевой случай — в его docstring).
                ранний_план_есть = (
                    _step_done(wd, EARLY_PLAN_STEP)
                    and (wd / "plan.json").is_file()
                )
                if ранний_план_есть:
                    early_gates = _frozen_plan_gates(_plan_before_avatar(
                        wd,
                        master.timed_scenario,
                        alignment_words=apply_caption_fixes(
                            list(master.words), caption_fixes),
                        # План монтажа нужен и здесь: по нему считается заказ,
                        # а по заказу — вердикт бюджета. Без него `D29` уходил
                        # бы в вечный SKIP на каждой пересборке.
                        edit_plan=edit_plan,
                        config=config,
                        agent_spend=agent_spend,
                    ).get("gates") or {})
            elif use_avatar_islands:
                avatar_plan_fn = avatar_plan_fn or _build_avatar_render_plan
                avatar_render_fn = avatar_render_fn or _render_avatar_islands
                # Работа 9: сперва план агента, и только потом заказ ведущей.
                # Секунды ведущей — самые дорогие в ролике, и заказывать их по
                # эвристике покрытия значит платить за кадры, которые агент
                # закроет вставкой. План ложится в ту же папку: сборка
                # подхватит его по маркеру шага и агента заново не позовёт.
                # Слова выравнивания правим той же картой, что уйдёт в
                # субтитры, — агент должен читать те же фразы, что увидит
                # зритель.
                early_plan = _plan_before_avatar(
                    wd,
                    master.timed_scenario,
                    alignment_words=apply_caption_fixes(
                        list(master.words), caption_fixes),
                    # План монтажа — вход заказа: по нему ранний шаг строит
                    # НАСТОЯЩИЙ заказ ведущей и им же судит бюджет. Своей
                    # оценки у гейта нет — она разошлась со счётом на 6,8 с.
                    edit_plan=edit_plan,
                    # Настройки клиента — те же, по которым пойдёт заказ:
                    # задание, гейты плана и счёт HeyGen обязаны считаться
                    # одной арифметикой (`avatar_islands` в config).
                    config=config,
                    agent_spend=agent_spend,
                )
                # Промахи плана — ведущая в открытии и финале, бюджет, роли
                # hook и cta, короткие фразы без ведущей, пропажа лица — агенту
                # уже вернули пересдачей внутри раннего плана. Заказ он
                # не отменяет — деньги считаны, ролик собирается, — но в отчёт
                # по сборке попасть обязан: иначе о нём не узнает никто.
                early_gates = early_plan.get("gates") or {}
                # Решение агента заменяет эвристику покрытия: фраза в сцене с
                # avatarNeeded: false уходит из заказа целиком. План на диске
                # переписываем — по нему потом судят гейты вставок.
                #
                # Спрашиваем сам заказ, а не цвет гейтов. Прежде любой красный
                # ранний гейт выбрасывал решение агента целиком — по замеру
                # «95 % таких расстановок роняют build_avatar_render_plan».
                # Прогон 06eb0a8f (01.09.2026) этот замер опроверг: бюджет
                # завернул план по выдуманному числу, а заказ по нему собрался
                # нормально, шестью шотами. Выброшенное решение развело план и
                # купленные клипы, сборка легла на `D12_faceless_cover` — $18
                # списаны, ролика нет. Гадать больше не о чем: заказ построен
                # ранним шагом, и он либо есть, либо его нет. Откат остался
                # ровно для второго случая — настоящего отказа.
                #
                # Порядок записи критичен: `save_edit_plan` идёт только вместе
                # с построенным заказом. Иначе `edit_plan.json` уедет вперёд, а
                # заказ заморозится по хэшу другого плана (`edit_plan_sha256`),
                # и возобновление прогона разойдётся с манифестом.
                заказ = early_plan.get("order") or {}
                if заказ.get("plan") is not None:
                    # Берём тот план монтажа, по которому заказ и посчитан, —
                    # второй проход `apply_agent_coverage` дал бы копию, чей
                    # хэш совпадает случайно, а не по построению.
                    edit_plan = заказ["edit_plan"]
                    save_edit_plan(edit_plan, wd)
                else:
                    print("[make] заказ ведущей по плану агента не собрался — "
                          "покрытие оставлено прежним: "
                          + (заказ.get("error")
                             or "ранний шаг заказ не строил"),
                          file=sys.stderr)
                master_sha256 = hashlib.sha256(
                    Path(master.wav).read_bytes()).hexdigest()
                avatar_render_plan = avatar_plan_fn(
                    edit_plan,
                    config,
                    master_audio_sha256=master_sha256,
                )
                save_avatar_render_plan(avatar_render_plan, wd)
                rendered = avatar_render_fn(
                    master.wav,
                    avatar_render_plan,
                    avatar_client,
                    wd,
                    cache_dir,
                    edit_plan=edit_plan,
                    meter=(meter.heygen if meter is not None else None),
                )
                avatar_mp4s = list(
                    rendered.clips if hasattr(rendered, "clips") else rendered
                )
                avatar_render_manifest = getattr(rendered, "manifest", None)
            else:
                for i, (b, wav) in enumerate(zip(scenario["blocks"], block_wavs)):
                    if fmt in ("split", "avatar"):
                        role = b.get("role")
                        billable = True
                        if role == "cta":
                            # Попадание в кэш проверяем ДО вызова: сам
                            # cached_generate возвращает путь одинаково в обоих
                            # случаях, и по нему хит от промаха не отличить.
                            key = avatar_cache_key(avatar_client, wav, role=role)
                            billable = not (cache_dir / f"{key}.mp4").exists()
                            mp4 = cached_generate(
                                avatar_client, wav, cache_dir, role=role
                            )
                        elif i in covered_blocks:
                            # Локальный ffmpeg, HeyGen не вызывается — не платно.
                            billable = False
                            mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                        else:
                            # role задаёт пластику: хук энергичный, payoff спокойный
                            mp4 = avatar_client.generate(
                                wav, wd / f"avatar_{i}.mp4", role=role
                            )
                        if meter is not None and billable:
                            meter.heygen(
                                billable_seconds(mp4),
                                twin=bool(getattr(avatar_client, "look_id", None)),
                            )
                        avatar_mp4s.append(mp4)
                    else:
                        voice_wavs.append(wav)
        except Exception as e:
            return fail("voice", e)

        if edit_cfg["jump_cuts"] and avatar_mp4s and not use_master_audio:
            # режем паузы ДО assemble: media_dur померяет уже подрезанные фрагменты,
            # retime_scenario построит сетку по ним, и субтитры со вставками сами
            # встанут на новые времена
            _log("jump_cuts")
            try:
                avatar_mp4s = jump_cut_fn(avatar_mp4s, wd)
            except Exception as e:
                return fail("jump_cuts", e)
        elif edit_cfg["jump_cuts"] and use_master_audio:
            # Покадровое удаление пауз из HeyGen-клипов разрушило бы immutable
            # master timeline. Вернуть jump cuts можно после timeline-aware версии.
            print(
                "[make] jump_cuts отключены: master audio является source of truth",
                file=sys.stderr,
            )

        _log("assemble")
        try:
            out_mp4 = wd / "reel.mp4"
            # Непрерывный видеоряд-источник (ingest) убран: аватар — единственный
            # формат, низовое видео сборщик больше не получает.
            res = assemble_fn(wd,
                              master.timed_scenario,
                              edit_plan=edit_plan,
                              avatar_mp4s=avatar_mp4s or [],
                              master_audio=master.wav,
                              alignment_words=apply_caption_fixes(
                                  list(master.words), caption_fixes),
                              avatar_render_plan=avatar_render_plan,
                              # Тот же кошелёк, что у раннего плана: работа
                              # агента монтажа — платный шаг наравне с HeyGen и
                              # озвучкой, и счёт у неё на весь прогон один.
                              agent_spend=agent_spend,
                              out_mp4=out_mp4)
            mp4 = res["mp4"]
            timed = res["timed_scenario"]
            words = res.get("words_fixed")
        except Exception as e:
            return fail("assemble", e)

        _log("verify")
        try:
            qa = verify_reel(Path(mp4), timed, words=words,
                             hypothesis=_fixes_hypothesis(config), format=fmt)
            # verify_reel не знает про вставки: гейты раскадровки приходят от
            # сборщика и вливаются в общий отчёт, чтобы qa_pass был честным.
            # Проверка плана до заказа аватара идёт первой: её ключи свои
            # (D28, D29), и сборка их не перекрывает.
            # Гейты готового файла — до слияния: причину пересборки пишем по
            # ним и по гейтам сборщика, а ранний план в неё не попадает.
            file_gates = dict(qa["gates"])
            qa["gates"].update(early_gates)
            qa["gates"].update(res.get("gates") or {})
            qa["all_pass"] = all(
                not str(v).startswith("FAIL") for v in qa["gates"].values())
            # Причину отказа пишем по ОБЪЕДИНЁННОМУ вердикту сборщика и
            # готового файла. Сборщик знает только свои гейты
            # (`hf_render.py:1409`), и когда ролик валят гейты файла
            # (D1_duration, D5_voice…), его строка выходит пустой и стирает
            # запись. Продолжение тогда получает то же задание без единого
            # слова о том, чем прошлый прогон не прошёл, — и отдаёт тот же
            # ролик за те же деньги. Пустая строка снимает запись: пройденные
            # проверки не должны гонять агента вечно.
            #
            # Гейты раннего плана сюда не идут намеренно: план заморожен
            # заказом ведущей (`plan.early.json`), пересборка его не меняет, и
            # такая причина висела бы на папке вечно.
            retry_gates = {**file_gates, **(res.get("gates") or {})}
            _save_retry_reason(wd, "; ".join(
                f"{name}: {verdict}" for name, verdict in retry_gates.items()
                if str(verdict).startswith("FAIL")))
        except Exception as e:
            return fail("verify", e)

        # `qa_pass: False` рядом с `ok: True` — штатный исход, не отказ
        # (решение 05): ведущая куплена, гейт остаётся FAIL честно, а решает,
        # доставлять ли ролик с изъяном, уже `bot.py` — здесь только отчёт.
        # `gates` и причина пересдачи (записана строкой выше) едут в него как
        # есть, красными вердиктами.
        return {
            "ok": True,
            "workdir": str(wd),
            "mp4": mp4,
            "qa_pass": qa["all_pass"],
            "qa_checked": True,
            "gates": qa["gates"],
            "avatar_summary": (
                avatar_render_plan.get("summary")
                if avatar_render_plan is not None else None
            ),
            "avatar_render_manifest": avatar_render_manifest,
            "stage": None,
            "error": None,
        }
    finally:
        if meter is not None:
            meter.claude_agent(agent_spend.runs, agent_spend.total_cost_usd)
