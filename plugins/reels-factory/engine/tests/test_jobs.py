"""Durable job queue: только SQLite и tmp_path, без сети и paid API."""
import json

from reels_factory.jobs import JobStore


def _store(tmp_path):
    return JobStore(tmp_path / "jobs.sqlite3", tmp_path / "jobs")


def test_job_получает_uuid_и_отдельную_папку(tmp_path):
    store = _store(tmp_path)

    first = store.enqueue(7)
    second = store.enqueue(8)

    assert first.job_id != second.job_id
    assert first.workdir == tmp_path / "jobs" / first.job_id
    assert second.workdir == tmp_path / "jobs" / second.job_id
    assert first.workdir.is_dir() and second.workdir.is_dir()


def test_prepared_job_видна_worker_только_после_записи_scenario(tmp_path):
    store = _store(tmp_path)
    job_id = store.new_id()
    workdir = store.workdir_for(job_id)
    workdir.mkdir(parents=True)
    scenario = {"blocks": [{"role": "hook", "speech": "Привет"}]}
    (workdir / "scenario.json").write_text(
        json.dumps(scenario, ensure_ascii=False), encoding="utf-8"
    )

    store.enqueue_prepared(7, job_id=job_id, workdir=workdir)
    claimed = store.claim_next()

    assert claimed.job_id == job_id
    assert json.loads((claimed.workdir / "scenario.json").read_text(encoding="utf-8")) == scenario


def test_queue_переживает_новый_instance_store(tmp_path):
    first_process = _store(tmp_path)
    queued = first_process.enqueue(7)

    after_restart = _store(tmp_path)
    loaded = after_restart.get(queued.job_id)

    assert loaded.status == "queued"
    assert loaded.chat_id == 7
    assert loaded.workdir == queued.workdir


def test_claim_атомарно_раздаёт_разные_jobs(tmp_path):
    producer = _store(tmp_path)
    first = producer.enqueue(7)
    second = producer.enqueue(8)

    worker_a = _store(tmp_path).claim_next()
    worker_b = _store(tmp_path).claim_next()

    assert {worker_a.job_id, worker_b.job_id} == {first.job_id, second.job_id}
    assert worker_a.status == worker_b.status == "running"
    assert _store(tmp_path).claim_next() is None


def test_active_for_chat_берёт_queued_или_running(tmp_path):
    store = _store(tmp_path)
    queued = store.enqueue(7)

    assert store.active_for_chat(7).job_id == queued.job_id
    store.claim_next()
    assert store.active_for_chat(7).status == "running"

    store.finish(queued.job_id, "completed", result={"ok": True})
    assert store.active_for_chat(7) is None
    assert store.latest_for_chat(7).result == {"ok": True}


def test_restart_не_повторяет_running_paid_job_автоматически(tmp_path):
    store = _store(tmp_path)
    running = store.enqueue(7)
    store.claim_next()
    still_queued = store.enqueue(8)

    interrupted = store.mark_running_interrupted()

    assert [job.job_id for job in interrupted] == [running.job_id]
    assert store.get(running.job_id).status == "interrupted"
    assert "повторной оплаты" in store.get(running.job_id).error
    assert store.get(still_queued.job_id).status == "queued"
    assert store.claim_next().job_id == still_queued.job_id


def test_qa_fail_терминальный_и_результат_сохраняется(tmp_path):
    store = _store(tmp_path)
    job = store.enqueue(7)
    store.claim_next()

    finished = store.finish(
        job.job_id,
        "qa_failed",
        result={"ok": True, "qa_pass": False, "gates": {"D1": "FAIL"}},
        stage="verify",
        error="QA gates failed",
    )

    assert finished.status == "qa_failed"
    assert finished.stage == "verify"
    assert finished.result["gates"]["D1"] == "FAIL"


def test_20_users_получают_20_изолированных_jobs(tmp_path):
    store = _store(tmp_path)
    expected = {}
    for chat_id in range(1, 21):
        job_id = store.new_id()
        workdir = store.workdir_for(job_id)
        workdir.mkdir(parents=True)
        (workdir / "owner.txt").write_text(str(chat_id), encoding="utf-8")
        job = store.enqueue_prepared(chat_id, job_id=job_id, workdir=workdir)
        expected[job.job_id] = chat_id

    claimed = []
    while True:
        job = store.claim_next()
        if job is None:
            break
        claimed.append(job)

    assert len(claimed) == 20
    assert len({job.job_id for job in claimed}) == 20
    assert len({job.workdir for job in claimed}) == 20
    for job in claimed:
        assert int((job.workdir / "owner.txt").read_text(encoding="utf-8")) == expected[job.job_id]


def test_audio_review_job_паузится_и_только_approve_возвращает_её_в_очередь(
        tmp_path):
    store = _store(tmp_path)
    job_id = store.new_id()
    workdir = store.workdir_for(job_id)
    workdir.mkdir(parents=True)
    created = store.enqueue_prepared(
        7,
        job_id=job_id,
        workdir=workdir,
        initial_status="audio_queued",
        initial_stage="audio_preview",
    )

    claimed_audio = store.claim_next()
    assert created.status == "audio_queued"
    assert claimed_audio.status == "audio_running"
    assert claimed_audio.stage == "audio_preview"

    waiting = store.transition(
        job_id,
        "awaiting_audio_approval",
        expected="audio_running",
        stage="audio_review",
    )
    assert waiting.status == "awaiting_audio_approval"
    assert store.claim_next() is None
    assert store.active_for_chat(7).job_id == job_id

    store.transition(
        job_id,
        "queued",
        expected="awaiting_audio_approval",
        stage="build",
    )
    claimed_render = store.claim_next()
    assert claimed_render.status == "running"
    assert claimed_render.stage == "build"
    assert claimed_render.attempts == 2


def test_restart_возвращает_локальную_обработку_voice_к_ожиданию(tmp_path):
    store = _store(tmp_path)
    job = store.enqueue(7)
    store.transition(
        job.job_id,
        "user_audio_processing",
        expected="queued",
        stage="user_audio",
    )

    recovered = store.recover_user_audio_processing()

    assert [item.job_id for item in recovered] == [job.job_id]
    current = store.get(job.job_id)
    assert current.status == "awaiting_user_audio"
    assert "пришлите голосовое ещё раз" in current.error


def test_cancel_waiting_отменяет_ждущую_но_щадит_идущую(tmp_path):
    store = _store(tmp_path)
    # job на паузе (ждёт юзера) — отменяется, уходит из активных
    jid = store.new_id()
    wd = store.workdir_for(jid)
    wd.mkdir(parents=True)
    (wd / "scenario.json").write_text(
        json.dumps({"blocks": [{"role": "hook", "speech": "Привет"}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    store.enqueue_prepared(
        7, job_id=jid, workdir=wd,
        initial_status="awaiting_audio_approval", initial_stage="audio_review",
    )
    cancelled = store.cancel_waiting(jid)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert store.active_for_chat(7) is None

    # job в реальном рендере — отмена не проходит (None), статус не меняется
    running = store.enqueue(8)
    store.claim_next()  # queued -> running
    assert store.cancel_waiting(running.job_id) is None
    assert store.get(running.job_id).status == "running"
