import pytest

from reels_factory.compose import (GRADE_FILTER, GRAIN_FILTER, build_finish_filter,
                                   build_video_filter)
from reels_factory.config import edit_settings
from reels_factory.edit import EditError, jump_cut, jump_cut_fragments


class _FakeRun:
    """Вместо auto-editor: записывает команду и создаёт выходной файл."""

    def __init__(self):
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        from pathlib import Path
        out = Path(cmd[cmd.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"cutmp4")


def _frag(tmp_path, name="avatar_0.mp4"):
    p = tmp_path / name
    p.write_bytes(b"mp4")
    return p


def test_jump_cut_зовёт_auto_editor_с_порогом_и_запасом(tmp_path):
    run = _FakeRun()
    src = _frag(tmp_path)

    out = jump_cut(src, tmp_path / "cut.mp4", threshold=0.05, margin_s=0.2, run=run)

    assert out.read_bytes() == b"cutmp4"
    cmd = run.cmds[0]
    assert "auto-editor" in cmd[0]
    assert "audio:threshold=0.05" in cmd
    assert "0.2s" in cmd
    # исходник не тронут — есть с чем сравнить результат
    assert src.read_bytes() == b"mp4"


def test_jump_cut_падает_если_исходника_нет(tmp_path):
    with pytest.raises(EditError, match="нет исходного фрагмента"):
        jump_cut(tmp_path / "нет.mp4", tmp_path / "out.mp4", run=_FakeRun())


def test_фрагменты_режутся_по_порядку(tmp_path):
    run = _FakeRun()
    frags = [_frag(tmp_path, f"avatar_{i}.mp4") for i in range(3)]

    out = jump_cut_fragments(frags, tmp_path / "r", run=run)

    assert len(out) == 3
    assert [p.name for p in out] == ["avatar_0_cut.mp4", "avatar_1_cut.mp4",
                                     "avatar_2_cut.mp4"]


def test_финишные_фильтры_собираются_в_нужном_порядке():
    assert build_finish_filter() == ""
    assert build_finish_filter(grade=True) == GRADE_FILTER
    assert build_finish_filter(grain=True) == GRAIN_FILTER
    # зерно всегда последним — поверх грейда, иначе цвет размажет шум
    assert build_finish_filter(grade=True, grain=True) == f"{GRADE_FILTER},{GRAIN_FILTER}"


def test_видеофильтр_без_флагов_не_меняется():
    assert build_video_filter("avatar").endswith("null[v]")


def test_видеофильтр_с_грейдом_и_зерном_вешает_их_на_выход():
    fc = build_video_filter("avatar", grade=True, grain=True)
    assert fc.endswith(f"{GRADE_FILTER},{GRAIN_FILTER}[v]")


def test_монтаж_по_умолчанию_выключен():
    cfg = edit_settings({})
    assert cfg["jump_cuts"] is False
    assert cfg["grade"] is False
    assert cfg["grain"] is False


def test_флаги_читаются_из_конфига_а_опечатки_игнорируются():
    cfg = edit_settings({"edit": {"jump_cuts": True, "непонятный_ключ": 1}})
    assert cfg["jump_cuts"] is True
    assert cfg["grade"] is False
    assert "непонятный_ключ" not in cfg


def test_музыка_идёт_с_дакингом_под_голосом():
    from reels_factory.edit import build_music_filter

    f = build_music_filter()
    # без сайдчейна музыка либо забивает речь, либо не слышна вовсе
    assert "sidechaincompress" in f
    assert "alimiter" in f


def test_план_собирается_одним_проходом_ffmpeg(tmp_path):
    from reels_factory.edit import apply_plan

    cmds = []

    def fake_run(cmd):
        cmds.append(cmd)
        out = Path(cmd[-1])
        out.write_bytes(b"rendered")

    from pathlib import Path
    src = tmp_path / "in.mp4"
    src.write_bytes(b"mp4")
    plan = {"duration": 10.0, "punch": [(2.0, 0.6), (5.0, 0.6)], "whoosh": []}

    out = apply_plan(src, tmp_path / "out.mp4", plan, grade=True, grain=True,
                     run=fake_run)

    assert out.read_bytes() == b"rendered"
    assert len(cmds) == 1  # каждый лишний проход — ещё одна перекодировка
    fc = cmds[0][cmds[0].index("-filter_complex") + 1]
    assert "crop=iw/" in fc          # наезды
    assert "eq=contrast" in fc       # цвет
    assert "noise=alls" in fc        # зерно


def test_свуши_подмешиваются_на_времена_плана(tmp_path):
    from pathlib import Path

    from reels_factory.edit import apply_plan

    cmds = []

    def fake_run(cmd):
        cmds.append(cmd)
        Path(cmd[-1]).write_bytes(b"r")

    src = tmp_path / "in.mp4"
    src.write_bytes(b"mp4")
    whoosh = tmp_path / "whoosh.wav"
    whoosh.write_bytes(b"wav")
    plan = {"duration": 10.0, "punch": [(2.0, 0.6)], "whoosh": [2.0]}

    apply_plan(src, tmp_path / "out.mp4", plan, whoosh_wav=whoosh, run=fake_run)

    fc = cmds[0][cmds[0].index("-filter_complex") + 1]
    assert "adelay=2000|2000" in fc
