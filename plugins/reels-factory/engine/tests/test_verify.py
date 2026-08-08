"""QA-гейты рилса (verify_reel). Только DI-замеры — без ffmpeg."""
from reels_factory.verify import verify_reel


def _scenario(total_end=25.0):
    # ретаймленный сценарий: D1 сверяет длительность mp4 с "total",
    # D5 — окно первой реплики [hook.start, hook.end-pause]
    return {"total": total_end, "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "pause_after": 0.5},
        {"role": "development", "start": 3.0, "end": total_end - 3.0},
        {"role": "cta", "start": total_end - 3.0, "end": total_end},
    ]}


def _vol_ok(f, start, end):
    return -20.0  # громко везде


def _prep(tmp_path):
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"")
    (tmp_path / "caps.ass").write_text("", encoding="utf-8")
    return mp4


def test_все_гейты_проходят(tmp_path):
    mp4 = _prep(tmp_path)
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["all_pass"] is True
    for g in ("D1_duration", "D2_resolution", "D3_loudness", "D5_voice"):
        assert report["gates"][g].startswith("PASS")
    assert report["gates"]["D4_captions"] == "PASS"


def test_d4_без_caps_ass_skip_а_не_fail(tmp_path):
    # Revideo вшивает субтитры в картинку и не создаёт caps.ass —
    # отсутствие файла больше не должно валить D4 (проверка вшитых сабов — D7)
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"")  # caps.ass рядом намеренно не создаём
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["gates"]["D4_captions"].startswith("SKIP")
    assert report["all_pass"] is True  # SKIP не проваливает набор


def test_провал_по_длительности(tmp_path):
    mp4 = _prep(tmp_path)
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 5.0, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["all_pass"] is False
    assert report["gates"]["D1_duration"].startswith("FAIL")


def test_60s_ролик_с_60s_сценарием_проходит_гейт_длительности(tmp_path):
    # раньше окно 14-40с валило бы это даже при точном совпадении со сценарием
    mp4 = _prep(tmp_path)
    report = verify_reel(
        mp4, _scenario(60.0),
        dur_fn=lambda f: 60.0, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["gates"]["D1_duration"].startswith("PASS")


def test_60s_ролик_с_30s_сценарием_валит_гейт_длительности(tmp_path):
    mp4 = _prep(tmp_path)
    report = verify_reel(
        mp4, _scenario(30.0),
        dur_fn=lambda f: 60.0, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["gates"]["D1_duration"].startswith("FAIL")
    assert "расходится с сценарием" in report["gates"]["D1_duration"]


def test_провал_по_тишине_голоса(tmp_path):
    mp4 = _prep(tmp_path)

    def vol(f, start, end):
        # тихо в окне первой реплики [0.3, 2.2], громко в паузе после хука [2.5,3.0]
        return -68.0 if start < 2.0 else -18.0

    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=vol,
    )
    assert report["all_pass"] is False
    assert report["gates"]["D5_voice"].startswith("FAIL")


def test_d6_снят_и_тишина_видеоряда_не_фейлит(tmp_path):
    """D6 мерил звук бирол-слоя консольного конвейера; в пути HyperFrames
    вставки звука не несут по устройству, и гейт валился на каждом прогоне."""
    mp4 = _prep(tmp_path)

    def vol(f, start, end):
        # после хука тихо — раньше это валило D6
        return -67.0 if start > 2.0 else -18.0

    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=vol,
    )
    assert "D6_broll_bed" not in report["gates"]
    assert report["all_pass"] is True


def test_d7_ловит_непочиненный_вариант_бренда(tmp_path):
    mp4 = _prep(tmp_path)
    words = [{"start": 0.0, "end": 0.3, "text": "гайт"}]
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
        words=words,
        hypothesis={"theme": "кофе", "theme_spoken": "кофе",
                    "brand_captions": {"Гайд": ["гайт"]}},
    )
    assert report["all_pass"] is False
    assert report["gates"]["D7_captions"].startswith("FAIL")
    assert "гайт" in report["gates"]["D7_captions"]


def test_d7_проходит_на_чистых_сабах(tmp_path):
    mp4 = _prep(tmp_path)
    words = [{"start": 0.0, "end": 0.3, "text": "Гайд"},
             {"start": 0.3, "end": 0.6, "text": "кофе"}]
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
        words=words,
        hypothesis={"theme": "кофе", "theme_spoken": "кофе",
                    "brand_captions": {"Гайд": ["гайт"]}},
    )
    assert report["all_pass"] is True
    assert report["gates"]["D7_captions"] == "PASS()"


def test_d7_левенштейн_подозрение_не_фейлит(tmp_path):
    mp4 = _prep(tmp_path)
    words = [{"start": 0.0, "end": 0.3, "text": "гайты"}]  # близко к варианту "гайт", но не он
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
        words=words,
        hypothesis={"theme": "кофе", "theme_spoken": "кофе",
                    "brand_captions": {"Гайд": ["гайт"]}},
    )
    assert report["all_pass"] is True
    assert not report["gates"]["D7_captions"].startswith("FAIL")
