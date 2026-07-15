"""QA-гейты рилса (verify_reel). Только DI-замеры — без ffmpeg."""
from reels_factory.verify import verify_reel


def _scenario(total_end=25.0):
    # ретаймленный сценарий: D1 сверяет длительность mp4 с "total",
    # D5 — окно первой реплики [hook.start, hook.end-pause], D6 — пауза после хука
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
    for g in ("D1_duration", "D2_resolution", "D3_loudness", "D5_voice", "D6_broll_bed"):
        assert report["gates"][g].startswith("PASS")
    assert report["gates"]["D4_captions"] == "PASS"


def test_провал_по_длительности(tmp_path):
    mp4 = _prep(tmp_path)
    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 5.0, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=_vol_ok,
    )
    assert report["all_pass"] is False
    assert report["gates"]["D1_duration"].startswith("FAIL")


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
    assert report["gates"]["D6_broll_bed"].startswith("PASS")


def test_провал_по_тишине_слоя_видеоряда(tmp_path):
    mp4 = _prep(tmp_path)

    def vol(f, start, end):
        # слой видеоряда пропал в паузе после хука, голос — громко
        return -67.0 if start > 2.0 else -18.0

    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=vol,
    )
    assert report["all_pass"] is False
    assert report["gates"]["D6_broll_bed"].startswith("FAIL")


def test_тихая_сцена_не_фейлит_d6(tmp_path):
    mp4 = _prep(tmp_path)

    def vol(f, start, end):
        return -40.0 if start > 2.0 else -18.0  # -40 выше порога -50

    report = verify_reel(
        mp4, _scenario(25.0),
        dur_fn=lambda f: 24.5, wh_fn=lambda f: (1080, 1920),
        lufs_fn=lambda f: -14.2, fps_fn=lambda f: 30.0, volume_fn=vol,
    )
    assert report["all_pass"] is True
    assert report["gates"]["D6_broll_bed"].startswith("PASS")


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
