"""Precut-планировщик: покрытие блоков бироллом ДО генерации аватара.

CLIP подменяется детерминированными эмбеддингами (без torch/сети).
"""
import reels_factory.segment_plan as sp


def _scenario():
    return {"blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "агенты заменят рутину"},
        {"role": "development", "start": 4.0, "end": 14.0,
         "speech": "настраиваем автоматизацию процессов в компании"},
        {"role": "payoff", "start": 14.0, "end": 22.0, "speech": "всё работает само"},
        {"role": "cta", "start": 22.0, "end": 25.0, "speech": "подпишись"},
    ]}


def _index(dur=20.0, emb=(1.0, 0.0)):
    return {"clip_a.mp4": {"duration": dur, "embedding": list(emb)}}


def _fake_embed(monkeypatch, vec=(1.0, 0.0)):
    monkeypatch.setattr(sp.lib, "embed_text", lambda text: list(vec))


def test_покрывает_development_при_уверенном_матче(monkeypatch):
    _fake_embed(monkeypatch)
    plan = sp.plan_precut(_scenario(), {}, index=_index())

    assert len(plan["segments"]) == 1
    seg = plan["segments"][0]
    assert seg["role"] == "development" and seg["insert"] is True
    assert seg["clip"] == "clip_a.mp4"
    assert plan["est"]["covered_s"] == 10.0
    assert any("full_broll" in line for line in plan["log"])


def test_hook_payoff_cta_никогда_не_покрываются(monkeypatch):
    _fake_embed(monkeypatch)
    plan = sp.plan_precut(_scenario(), {}, index=_index())
    assert all(s["role"] in sp.COVERABLE_ROLES for s in plan["segments"])


def test_слабый_матч_блок_остаётся_аватарным(monkeypatch):
    # косинус 0 к эмбеддингу клипа (ортогональные вектора)
    _fake_embed(monkeypatch, vec=(0.0, 1.0))
    plan = sp.plan_precut(_scenario(), {}, index=_index())
    assert plan["segments"] == []


def test_короткий_клип_не_покрывает_блок(monkeypatch):
    _fake_embed(monkeypatch)
    # блок 10с, клип 12с < 10*1.25 — недостаточно с запасом
    plan = sp.plan_precut(_scenario(), {}, index=_index(dur=12.0))
    assert plan["segments"] == []


def test_пустой_индекс_план_пустой():
    plan = sp.plan_precut(_scenario(), {}, index={})
    assert plan["segments"] == []
    assert any("пуст" in l for l in plan["log"])


def test_clip_недоступен_деградация_без_покрытия(monkeypatch):
    def broken(text):
        raise ImportError("нет torch")
    monkeypatch.setattr(sp.lib, "embed_text", broken)
    plan = sp.plan_precut(_scenario(), {}, index=_index())
    assert plan["segments"] == []
    assert any("CLIP недоступен" in l for l in plan["log"])


def test_соседние_блоки_не_покрываются_оба(monkeypatch):
    _fake_embed(monkeypatch)
    scenario = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "хук"},
        {"role": "context", "start": 4.0, "end": 9.0, "speech": "контекст про ботов"},
        {"role": "development", "start": 9.0, "end": 19.0, "speech": "автоматизация"},
        {"role": "payoff", "start": 19.0, "end": 24.0, "speech": "вывод"},
        {"role": "cta", "start": 24.0, "end": 27.0, "speech": "подпишись"},
    ]}
    index = {"a.mp4": {"duration": 30.0, "embedding": [1.0, 0.0]},
             "b.mp4": {"duration": 30.0, "embedding": [1.0, 0.0]}}
    plan = sp.plan_precut(scenario, {}, index=index)
    # оба кандидата матчатся, но покрыт только один (длинный development)
    assert [s["role"] for s in plan["segments"]] == ["development"]


def test_ритм_варнинг_на_длинном_аватарном_отрезке(monkeypatch):
    _fake_embed(monkeypatch, vec=(0.0, 1.0))  # ничего не покрыто
    plan = sp.plan_precut(_scenario(), {}, index=_index())
    assert plan["_canonical_edit_plan"]["summary"]["covered_block_indexes"] == []


def test_один_клип_не_бронируется_дважды(monkeypatch):
    _fake_embed(monkeypatch)
    scenario = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "хук"},
        {"role": "context", "start": 4.0, "end": 9.0, "speech": "контекст"},
        {"role": "development", "start": 9.0, "end": 15.0, "speech": "развитие"},
        {"role": "payoff", "start": 15.0, "end": 20.0, "speech": "вывод"},
        {"role": "cta", "start": 20.0, "end": 23.0, "speech": "подпишись"},
    ]}
    plan = sp.plan_precut(scenario, {}, index=_index(dur=30.0))
    clips = [s["clip"] for s in plan["segments"]]
    assert len(clips) == len(set(clips))


def test_save_plan_пишет_json(tmp_path):
    p = sp.save_plan({"segments": [], "log": []}, tmp_path)
    assert p.exists() and p.name == "edit_plan.json"
    assert not (tmp_path / "segment_plan.json").exists()
