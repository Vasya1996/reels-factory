from reels_factory.editplan import (HOOK_S, PATTERN_BREAK_S, STATIC_LIMIT_S,
                                    detect_silences, plan_edit, speech_segments,
                                    validate_plan)


def test_паузы_разбираются_из_вывода_ffmpeg():
    out = ("[silencedetect] silence_start: 5.73415\n"
           "[silencedetect] silence_end: 6.034331 | silence_duration: 0.300181\n"
           "[silencedetect] silence_start: 10.544014\n"
           "[silencedetect] silence_end: 10.980635 | silence_duration: 0.436621\n")

    silences = detect_silences("x.mp4", run=lambda cmd: out)

    assert silences == [(5.73415, 6.034331), (10.544014, 10.980635)]


def test_куски_речи_между_паузами():
    segs = speech_segments(20.0, [(5.0, 5.5), (10.0, 10.4)])

    assert segs == [(0.0, 5.0), (5.5, 10.0), (10.4, 20.0)]


def test_план_ставит_наезды_на_начала_фраз():
    # после паузы 5.0-5.5 фраза начинается на 5.5 — там уже есть вдох и смена
    # интонации, наезд читается как задуманный
    plan = plan_edit(20.0, [(5.0, 5.5), (10.0, 10.4)])

    starts = [t for t, _ in plan["punch"]]
    assert 5.5 in starts and 10.4 in starts


def test_свуш_на_каждый_наезд():
    plan = plan_edit(20.0, [(5.0, 5.5)])

    assert plan["whoosh"] == [t for t, _ in plan["punch"]]


def test_хук_держится_плотнее_остального():
    plan = plan_edit(20.0, [])

    in_hook = [t for t, _ in plan["punch"] if t < HOOK_S]
    # в первые 3 секунды изменений больше, чем даёт обычный шаг 2 с
    assert len(in_hook) >= 2


def test_план_без_пауз_всё_равно_держит_ритм():
    plan = plan_edit(30.0, [])

    qa = validate_plan(plan)
    assert qa["all_pass"] is True
    assert qa["gates"]["rhythm_no_static"]["max_gap"] <= STATIC_LIMIT_S


def test_акценты_от_модели_попадают_в_план():
    plan = plan_edit(20.0, [], accents=[4.2, 12.7])

    starts = [t for t, _ in plan["punch"]]
    assert 4.2 in starts and 12.7 in starts


def test_гейт_ловит_статику():
    plan = {"duration": 20.0, "punch": [(1.0, 0.6)], "whoosh": []}

    qa = validate_plan(plan)

    assert qa["all_pass"] is False
    assert qa["gates"]["rhythm_no_static"]["pass"] is False
    assert qa["gates"]["rhythm_no_static"]["max_gap"] > STATIC_LIMIT_S


def test_гейт_ловит_мельтешение():
    punch = [(round(0.3 * i, 2), 0.6) for i in range(1, 60)]
    plan = {"duration": 20.0, "punch": punch, "whoosh": []}

    qa = validate_plan(plan)

    assert qa["gates"]["rhythm_density"]["pass"] is False
    assert qa["gates"]["rhythm_density"]["per_10s"] > 8


def test_гейт_не_пускает_вставку_на_хук():
    plan = plan_edit(20.0, [])

    qa = validate_plan(plan, insert_windows=[(1.0, 4.0)])

    assert qa["gates"]["hook_uncovered"]["pass"] is False
    assert validate_plan(plan, insert_windows=[(6.0, 9.0)])["gates"]["hook_uncovered"]["pass"]


def test_гейт_ограничивает_число_вставок():
    plan = plan_edit(30.0, [])
    many = [(5.0, 7.0), (9.0, 11.0), (13.0, 15.0), (17.0, 19.0)]

    assert validate_plan(plan, insert_windows=many)["gates"]["inserts_count"]["pass"] is False
    assert validate_plan(plan, insert_windows=many[:3])["gates"]["inserts_count"]["pass"]


def test_паттерн_прерывание_не_реже_пятнадцати_секунд():
    plan = plan_edit(60.0, [])
    qa = validate_plan(plan)

    assert qa["gates"]["pattern_break"]["pass"] is True
    assert qa["gates"]["pattern_break"]["limit"] == PATTERN_BREAK_S


# --- ритм-добивка: панчи в статические дыры ---

def test_fill_static_gaps_пустое_покрытие_панч_каждые_три_секунды():
    from reels_factory.editplan import fill_static_gaps

    punches = fill_static_gaps([], 10.0)
    times = [t for t, _ in punches]
    assert times[0] == 3.0
    assert all(b - a <= 3.7 for a, b in zip(times, times[1:]))  # шаг max_gap+dur


def test_fill_static_gaps_закрытые_интервалы_не_добиваются():
    from reels_factory.editplan import fill_static_gaps

    # движение есть всё время — добивать нечего
    assert fill_static_gaps([(0.0, 10.0)], 10.0) == []


def test_fill_static_gaps_панч_только_в_дыре():
    from reels_factory.editplan import fill_static_gaps

    punches = fill_static_gaps([(0.0, 4.0), (12.0, 20.0)], 20.0)
    times = [t for t, _ in punches]
    assert times  # дыра 4..12 длиннее 3с — добита
    assert all(4.0 < t < 12.0 for t in times)


def test_fill_static_gaps_пересекающиеся_интервалы_сливаются():
    from reels_factory.editplan import fill_static_gaps

    # два куска покрывают 0..9 без дыр — панчей нет (ролик 9с)
    assert fill_static_gaps([(0.0, 5.0), (4.0, 9.0)], 9.0) == []
