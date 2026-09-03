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


# --- возобновление упавшей сборки -------------------------------------------
#
# Упавшую job человек продолжает с места остановки: папка цела, пройденные
# шаги помечены маркерами, утверждённая озвучка и клипы ведущей на месте.
# Через enqueue у такой сборки дороги назад нет: workdir UNIQUE не даст завести
# вторую job на ту же папку, а transition ходит только между активными
# статусами.

def _упавшая(store, chat_id=7, status="failed", stage="build"):
    """Job, дошедшая до реальной работы и закончившаяся терминально."""
    job = store.enqueue(chat_id)
    store.claim_next()
    return store.finish(job.job_id, status, stage=stage, error="упало")


def test_requeue_возвращает_возобновимую_сборку_в_ту_же_папку(tmp_path):
    """Без requeue упавшая job — тупик: transition умеет только активные
    статусы, а второй enqueue на ту же папку отобьёт UNIQUE(workdir). Тогда
    человеку остаётся новая сборка с нуля — то есть новая оплата озвучки и
    ведущей за то, что уже лежит готовым в старой папке."""
    from reels_factory.jobs import RESUMABLE_STATUSES

    assert set(RESUMABLE_STATUSES) == {
        "failed", "qa_failed", "delivery_failed", "interrupted"
    }

    for status in RESUMABLE_STATUSES:
        store = _store(tmp_path / status)
        упавшая = _упавшая(store, status=status)

        возвращённая = store.requeue(упавшая.job_id)

        assert возвращённая is not None, status
        assert возвращённая.status == "queued", status
        assert возвращённая.stage == "build", status
        # Папка та же: в ней утверждённая озвучка, маркеры шагов и клипы.
        assert возвращённая.workdir == упавшая.workdir, status
        взятая = store.claim_next()
        assert взятая.job_id == упавшая.job_id, status
        assert взятая.workdir == упавшая.workdir, status


def test_requeue_молчит_на_отменённой_и_доставленной(tmp_path):
    """Отменённую человек остановил сам, доставленную уже получил в чат:
    возвращать в очередь нечего — второй прогон только потратит деньги."""
    store = _store(tmp_path)
    отменённая = _упавшая(store, chat_id=7, status="cancelled")
    доставленная = _упавшая(store, chat_id=8, status="completed")

    assert store.requeue(отменённая.job_id) is None
    assert store.requeue(доставленная.job_id) is None
    assert store.get(отменённая.job_id).status == "cancelled"
    assert store.get(доставленная.job_id).status == "completed"
    assert store.claim_next() is None


def test_requeue_отсутствующей_job_ничего_не_создаёт(tmp_path):
    """Номер сборки приходит с кнопки из истории чата — он может быть чужим
    или уже несуществующим."""
    store = _store(tmp_path)

    assert store.requeue("нет-такой-job") is None
    assert store.claim_next() is None


def test_повторный_requeue_не_плодит_вторую_сборку(tmp_path):
    """Кнопка живёт в истории чата вечно, и по ней тапают дважды. Вторая
    постановка в очередь дала бы два прогона на одной папке разом."""
    store = _store(tmp_path)
    упавшая = _упавшая(store)

    первый = store.requeue(упавшая.job_id)
    второй = store.requeue(упавшая.job_id)

    assert первый is not None and второй is None
    with store._connect() as conn:
        всего = conn.execute(
            "SELECT COUNT(*) AS n FROM build_jobs WHERE chat_id = 7"
        ).fetchone()["n"]
    assert всего == 1
    assert store.claim_next().job_id == упавшая.job_id
    assert store.claim_next() is None


def test_возобновление_увеличивает_число_попыток(tmp_path):
    """По числу попыток бот решает, показывать ли кнопку продолжения: вечно
    перезапускать сборку, которая падает каждый раз, незачем."""
    store = _store(tmp_path)
    упавшая = _упавшая(store)
    assert упавшая.attempts == 1

    store.requeue(упавшая.job_id)
    снова_взята = store.claim_next()

    assert снова_взята.attempts == 2


def test_рестарт_не_затирает_настоящую_стадию_прерванной_job(tmp_path):
    """Стадия — единственное, по чему потом видно, ЧЕМ была занята сборка.

    `mark_running_interrupted` забирает разом и `audio_running`, и `running`, и
    обоим ставит `stage='restart'`. Настоящая стадия (`audio_preview` у
    озвучки) при этом теряется, а бот отсекает по ней именно те сборки, где
    продолжать нечего: с затёртой стадией прерванная озвучка получает кнопку
    продолжения и уезжает в общую очередь — то есть в монтаж, мимо утверждения
    озвучки человеком.
    """
    store = _store(tmp_path)

    job_id = store.new_id()
    workdir = store.workdir_for(job_id)
    workdir.mkdir(parents=True)
    озвучка = store.enqueue_prepared(
        7, job_id=job_id, workdir=workdir,
        initial_status="audio_queued", initial_stage="audio_preview",
    )
    сборка = store.enqueue(8)
    assert store.claim_next().job_id == озвучка.job_id
    assert store.claim_next().job_id == сборка.job_id
    # Стадию ставит сам claim_next — это и есть «настоящая».
    assert store.get(озвучка.job_id).stage == "audio_preview"
    assert store.get(сборка.job_id).stage == "build"

    прерванные = store.mark_running_interrupted()

    assert {job.job_id for job in прерванные} == {озвучка.job_id, сборка.job_id}
    assert store.get(озвучка.job_id).status == "interrupted"
    assert store.get(сборка.job_id).status == "interrupted"
    assert store.get(озвучка.job_id).stage == "audio_preview"
    assert store.get(сборка.job_id).stage == "build"
    # То же самое в списке, который читает бот, — по нему он рисует кнопки.
    assert {job.job_id: job.stage for job in прерванные} == {
        озвучка.job_id: "audio_preview", сборка.job_id: "build",
    }
    # Причину рестарта человек всё так же должен видеть.
    assert "повторной оплаты" in store.get(озвучка.job_id).error


def test_meta_сохраняется_и_переживает_рестарт_store(tmp_path):
    store = _store(tmp_path)
    job_id = store.new_id()
    workdir = store.workdir_for(job_id)
    workdir.mkdir(parents=True)

    store.enqueue_prepared(
        7, job_id=job_id, workdir=workdir,
        meta={"username": "vasya", "first_name": "Вася"},
    )

    заново = JobStore(tmp_path / "jobs.sqlite3", tmp_path / "jobs")
    assert заново.get(job_id).meta == {"username": "vasya", "first_name": "Вася"}


def test_job_без_meta_читается_пустой(tmp_path):
    store = _store(tmp_path)

    job = store.enqueue(7)  # enqueue не передаёт meta — как ручной/старый вызов

    assert job.meta is None
    assert store.get(job.job_id).meta is None


def test_старая_база_без_колонки_meta_json_переживает_миграцию(tmp_path):
    """Боевая очередь уже лежит на диске без этой колонки (задача из
    независимой проверки пачки 08-10) — ALTER в _init_db обязан добавить её,
    не потеряв старые строки."""
    import sqlite3

    db_path = tmp_path / "jobs.sqlite3"
    workdir = tmp_path / "jobs" / "старая-job"
    workdir.mkdir(parents=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE build_jobs (
                job_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                workdir TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                resumes INTEGER NOT NULL DEFAULT 0,
                stage TEXT,
                error TEXT,
                result_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO build_jobs (job_id, chat_id, workdir, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 1.0, 1.0)",
            ("старая-job", 7, str(workdir.resolve()), "queued"),
        )

    store = JobStore(db_path, tmp_path / "jobs")

    старая = store.get("старая-job")
    assert старая is not None
    assert старая.meta is None  # мигрировавшая колонка пуста, не падает

    новая = store.enqueue(8)
    assert новая.meta is None
