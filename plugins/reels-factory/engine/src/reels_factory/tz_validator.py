"""Валидатор-линтер монтажного tz (Модуль B, финальный шаг перед рендером).

ПОСЛЕ УДАЛЕНИЯ РЕНДЕРЕРА REVIDEO tz.json НИКТО НЕ ПРОИЗВОДИТ: у модуля остались
только собственные тесты (`tests/test_tz_validator.py`). Оставлен намеренно —
судьба формата задания решается отдельно.

Дублирует правила, зашитые в прежний движок, как проверки на уровне плана:
поймать проблему в tz до рендера дешевле, чем разглядывать её в готовом mp4. Часть нарушений чинится автоматически (безопасные правки — обрезать
хвост, заменить длинное тире), часть — предупреждение с предложением.

Уровни: ERROR (сломает рендер/картинку), WARN (стилевой риск), FIXED (автофикс
применён). Отчёт можно печатать в лог; ERROR'ы — повод не рендерить.

Правила (из docs/TZ_pipeline_v6.md, синхронно с движком):
  * флеш-кадры: нет шота короче MIN_SHOT=1.2с, зажатого между двумя;
  * зумы: каждый тип camera ≤1 раз за ролик;
  * эффекты: соседние сегменты не одного типа; b-roll-стили чередуются;
  * подложка: cover-оверлей поверх лица → бэкплейт (движок мостит при зазоре
    < MIN_SHOT; валидатор предупреждает, если мостика не будет);
  * b-roll: src заполнен, клип не короче окна, без повторов клипа;
  * бренд: вотермарк включён, без длинного тире (правило стиля).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Синхронно с project.tsx.
MIN_SHOT = 1.2                      # с — короче между двумя другими = флеш-кадр
_COVER_TYPES = {
    "broll_bg_particles",
    "chart_bars",
    "complexity_cloud",
    "persona_card",
    "value_layers",
    "concept_nodes",
    "sequence_flow",
}  # полноэкранные оверлеи (для бэкплейта)
# Эффекты с видео-источником (нужен src-клип). chart_bars — cover, но это
# инфографика (items), а не видео, поэтому src ему НЕ требуется.
_VIDEO_SRC_TYPES = {"broll", "broll_bg_particles"}
_ZOOMS = {"zoom_out", "punch", "push", "snap_zoom", "ken_burns", "pulse", "shake_zoom"}
# Резкие/мельтешащие зумы (правило Юлии: не использовать; движение — дрейфом).
_HARSH_ZOOMS = {"snap_zoom", "shake_zoom", "pulse", "punch"}
# Минимальная длительность любого биролла (короче — мельтешит).
MIN_BROLL_S = 3.0
# Минимальная длина сегмента, где ещё влезает подпись (короче — текст не прочитать).
_MIN_CAPTION_SHOT = 0.6
_LONG_DASHES = ("—", "–")          # длинное/среднее тире — правило стиля: не использовать
# Ритм (бест-практис): говорящая голова без b-roll-вставки не дольше этого.
RHYTHM_MAX_AVATAR_S = 10.0
# Допуск на стыках precut-покрытия (округления таймингов).
_COVER_EPS = 0.05

ERROR, WARN, FIXED = "error", "warn", "fixed"


@dataclass
class Issue:
    level: str
    rule: str
    seg_id: int | None
    message: str


@dataclass
class ValidationReport:
    tz: dict
    issues: list = field(default_factory=list)

    def add(self, level, rule, seg_id, message):
        self.issues.append(Issue(level, rule, seg_id, message))

    @property
    def errors(self):
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warns(self):
        return [i for i in self.issues if i.level == WARN]

    @property
    def fixed(self):
        return [i for i in self.issues if i.level == FIXED]

    @property
    def ok(self) -> bool:
        return not self.errors

    def lines(self) -> list[str]:
        sym = {ERROR: "✗", WARN: "!", FIXED: "✎"}
        return [f"{sym.get(i.level, '·')} [{i.rule}] "
                f"{('seg#' + str(i.seg_id) + ' ') if i.seg_id is not None else ''}{i.message}"
                for i in self.issues]


def _is_cover(seg: dict) -> bool:
    eff = seg.get("effect") or {}
    return eff.get("type") in _COVER_TYPES or (
        eff.get("type") == "broll" and eff.get("style") == "fullscreen")


def _fix_dashes(s: str) -> tuple[str, bool]:
    out = s
    for d in _LONG_DASHES:
        out = out.replace(d, "-")
    return out, (out != s)


def validate_tz(tz: dict, *, index: dict | None = None,
                autofix: bool = True,
                covered_ranges: list | None = None) -> ValidationReport:
    """Проверить (и по возможности починить) tz. Возвращает отчёт.

    covered_ranges — [(start, end)] блоков precut-покрытия: аватар для них не
    генерился (base — чёрный кадр), любой зазор в fullscreen-покрытии или
    эффект, рисующий base (bubble, pip), там = чёрный экран в готовом ролике.
    """
    rep = ValidationReport(tz=tz)
    segs = tz.get("segments") or []
    duration = float((tz.get("meta") or {}).get("duration") or 0.0)

    # ---- бренд ----
    brand = tz.get("brand") or {}
    if not (brand.get("watermark") or "").strip():
        rep.add(WARN, "brand", None, "пустой watermark — вотермарк не появится")

    if autofix:
        for seg in segs:
            eff = seg.get("effect") or {}
            if "title" in eff:
                eff["title"], ch = _fix_dashes(str(eff["title"]))
                if ch:
                    rep.add(FIXED, "brand-dash", seg.get("id"), "длинное тире в title → '-'")
        caps = tz.get("captions") or {}
        kws = caps.get("keywords") or []
        fixed_kw = False
        for k in range(len(kws)):
            kws[k], ch = _fix_dashes(str(kws[k]))
            fixed_kw = fixed_kw or ch
        if fixed_kw:
            rep.add(FIXED, "brand-dash", None, "длинное тире в keywords → '-'")

    used_zooms: dict[str, int] = {}
    used_clips: dict[str, int] = {}

    for idx, seg in enumerate(segs):
        sid = seg.get("id")
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        window = end - start
        eff = seg.get("effect") or {}
        etype = eff.get("type")
        prev = segs[idx - 1] if idx > 0 else None
        nxt = segs[idx + 1] if idx + 1 < len(segs) else None

        # ---- границы сегмента ----
        if end <= start:
            rep.add(ERROR, "timeline", sid, f"end<=start ({start}..{end})")
        if duration and end > duration + 0.05:
            rep.add(ERROR, "timeline", sid, f"сегмент за пределами ролика (end={end}>{duration})")

        # ---- флеш-кадр: короткий шот, зажатый между двумя ----
        if prev and nxt and window < MIN_SHOT:
            rep.add(WARN, "flash-frame", sid,
                    f"шот {window:.2f}с < {MIN_SHOT}с между двумя — риск мелькания")

        # ---- зумы: каждый тип ≤1 ----
        ztype = (seg.get("camera") or {}).get("type")
        if ztype in _ZOOMS:
            used_zooms[ztype] = used_zooms.get(ztype, 0) + 1
            if used_zooms[ztype] == 2:
                rep.add(WARN, "zoom-repeat", sid, f"зум '{ztype}' повторяется (каждый тип ≤1 раз)")

        # ---- соседние эффекты не одного типа ----
        if prev and etype and etype != "none":
            peff = prev.get("effect") or {}
            if peff.get("type") == etype:
                if etype == "broll" and peff.get("style") != eff.get("style"):
                    pass  # разные b-roll-стили подряд допустимы (чередование)
                else:
                    rep.add(WARN, "effect-adjacent", sid,
                            f"два '{etype}' подряд — приёмы не чередуются")

        # ---- подложка под cover-оверлей ----
        if _is_cover(seg):
            bridged_in = prev is not None and _is_cover(prev) and (start - float(prev.get("end", 0))) < MIN_SHOT
            bridged_out = nxt is not None and _is_cover(nxt) and (float(nxt.get("start", 0)) - end) < MIN_SHOT
            if not (bridged_in or bridged_out):
                # одиночный cover — движок кладёт свой бэкплейт внутри эффекта, ок;
                # флажок только если рядом НЕ-cover впритык (лицо мелькнёт < MIN_SHOT)
                near = ((prev and not _is_cover(prev) and (start - float(prev.get("end", 0))) < MIN_SHOT)
                        or (nxt and not _is_cover(nxt) and (float(nxt.get("start", 0)) - end) < MIN_SHOT))
                if near:
                    rep.add(WARN, "backplate", sid,
                            "cover-оверлей впритык к лицу (<1.2с) — проверить бэкплейт/зазор")

        # ---- подпись в слишком коротком сегменте ----
        if seg.get("caption") not in (None, "hidden") and 0 < window < _MIN_CAPTION_SHOT:
            rep.add(WARN, "caption-bounds", sid,
                    f"подпись в шоте {window:.2f}с — не успеет прочитаться")

        # ---- эмодзи запрещены (правило стиля: смотрятся дёшево) ----
        if etype == "emoji_pop_sequence":
            if autofix:
                seg["effect"] = {"type": "none"}
                etype = "none"
                rep.add(FIXED, "emoji-banned", sid, "эмодзи убраны (правило стиля) → effect none")
            else:
                rep.add(ERROR, "emoji-banned", sid, "эмодзи в монтаже не используются")

        # ---- резкие зумы запрещены (движение только дрейфом ken_burns) ----
        if ztype in _HARSH_ZOOMS:
            rep.add(WARN, "harsh-zoom", sid,
                    f"резкий зум '{ztype}' — заменить на дрейф ken_burns/hold")

        # ---- биролл: минимум MIN_BROLL_S и не в хуке (первую фразу открываем лицом) ----
        if etype in _VIDEO_SRC_TYPES:
            if 0 < window < MIN_BROLL_S:
                rep.add(WARN, "broll-min-len", sid,
                        f"биролл {window:.1f}с < {MIN_BROLL_S:.0f}с — мельтешит, удлини окно")
            if seg.get("beat") == "hook":
                rep.add(WARN, "broll-first-phrase", sid,
                        "биролл в хуке — первую фразу открываем лицом, без биролла")

        # ---- смысловая инфографика не должна делить экран с субтитрами ----
        # Текст уже является частью композиции, поэтому второй текстовый слой
        # ухудшает читаемость. Видео-cover допускает обычные субтитры.
        semantic_types = _COVER_TYPES - {"broll_bg_particles"}
        if etype in semantic_types and seg.get("caption") not in (None, "hidden"):
            if autofix:
                seg["caption"] = "hidden"
                rep.add(FIXED, "caption-overlay", sid,
                        f"{etype} + субтитры → наложение на визуал; caption→hidden")
            else:
                rep.add(WARN, "caption-overlay", sid,
                        f"{etype} с видимой подписью — субтитры наложатся на инфографику")

        # ---- мелкий текстовый оверлей поверх лица налезает на субтитры ----
        # chat_bubble («message»-пузырь с текстом) дублирует субтитры и ложится на
        # них. Текст на экране допустим только как инфографика (chart_bars),
        # анимация (emoji) или полноэкранное видео (broll) — не мелкий пузырь.
        if etype == "chat_bubble":
            if autofix:
                seg["effect"] = {"type": "none"}
                etype = "none"
                rep.add(FIXED, "text-overlay", sid,
                        "chat_bubble убран — мелкий текст налезает на субтитры")
            else:
                rep.add(WARN, "text-overlay", sid,
                        "chat_bubble — текстовый оверлей налезает на субтитры")

        # ---- b-roll: src, длина, повторы (только видео-эффекты) ----
        if etype in _VIDEO_SRC_TYPES:
            src = eff.get("src")
            weak = eff.get("broll_weak_match")
            if not src:
                lvl = WARN if weak else ERROR
                rep.add(lvl, "broll-src", sid,
                        "нет src у b-roll" + (" (слабый матч, будет фолбэк)" if weak else ""))
            else:
                used_clips[src] = used_clips.get(src, 0) + 1
                if used_clips[src] == 2:
                    rep.add(WARN, "broll-dup", sid, f"клип '{src}' используется повторно")
                if index and src in index:
                    dur = float(index[src].get("duration") or 0.0)
                    off = float(eff.get("offset") or 0.0)
                    if dur and (dur - off) + 0.3 < window:
                        rep.add(WARN, "broll-short", sid,
                                f"клип '{src}' короче окна ({dur - off:.1f}с<{window:.1f}с) — замрёт")

    # ---- precut-покрытие: чёрный base закрыт на 100%, без эффектов из base ----
    for cs, ce in covered_ranges or []:
        cs, ce = float(cs), float(ce)
        overlapping = [s for s in segs
                       if float(s.get("end", 0)) > cs + _COVER_EPS
                       and float(s.get("start", 0)) < ce - _COVER_EPS]
        covers = sorted((s for s in overlapping if _is_cover(s)),
                        key=lambda s: float(s.get("start", 0)))
        pos = cs
        for s in covers:
            if float(s.get("start", 0)) > pos + _COVER_EPS:
                rep.add(ERROR, "covered-gap", s.get("id"),
                        f"зазор {pos:.2f}-{float(s['start']):.2f}с в покрытии "
                        f"precut-блока [{cs:.2f}-{ce:.2f}] — чёрный экран")
            pos = max(pos, float(s.get("end", 0)))
        if pos < ce - _COVER_EPS:
            rep.add(ERROR, "covered-gap", None,
                    f"хвост {pos:.2f}-{ce:.2f}с precut-блока не покрыт — чёрный экран")
        for s in overlapping:
            eff = s.get("effect") or {}
            if eff.get("bubble"):
                rep.add(ERROR, "covered-base", s.get("id"),
                        "bubble внутри precut-блока — пузырь нарисует чёрный base")
            if eff.get("type") == "broll" and eff.get("style") == "pip":
                rep.add(ERROR, "covered-base", s.get("id"),
                        "pip внутри precut-блока — фоном будет чёрный base")

    # ---- ритм: не дольше 10с одной говорящей головы без смены visual state ----
    marks = sorted((float(s.get("start", 0)), float(s.get("end", 0)))
                   for s in segs
                   if _is_cover(s))
    pos = 0.0
    for bs, be in marks:
        if bs - pos > RHYTHM_MAX_AVATAR_S:
            rep.add(WARN, "broll-rhythm", None,
                    f"{pos:.1f}-{bs:.1f}с: {bs - pos:.1f}с без visual state change "
                    f"(правило ≤{RHYTHM_MAX_AVATAR_S:.0f}с) — добавь вставку")
        pos = max(pos, be)
    if duration and duration - pos > RHYTHM_MAX_AVATAR_S:
        rep.add(WARN, "broll-rhythm", None,
                f"{pos:.1f}-{duration:.1f}с: {duration - pos:.1f}с без visual state change "
                f"(правило ≤{RHYTHM_MAX_AVATAR_S:.0f}с) — добавь вставку")

    return rep
