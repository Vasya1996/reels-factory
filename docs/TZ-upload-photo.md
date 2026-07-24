# ТЗ: загрузка фото аватара в HeyGen из кода (команда `upload-photo`)

Дата: 2026-07-24. Статус: к реализации.

## 1. Зачем

Сейчас путь «фото → HeyGen asset_id» существует только как ручной шаг мастера
`/reels-factory:setup` (шаг 5): интерактивная сессия Claude загружает фото
однострочником. В движке функции нет, в CLI команды нет.

Для ТГ-бота (2 клиента, каждый со своим аватаром) нужен программный шаг:
бот принял фото из чата → вызвал CLI → фото в HeyGen → `asset_id` записан в
профиль клиента → дальше обычный `make --client <id>`.

## 2. Объём

**Делаем:**
- функция загрузки фото-ассета в движке (`avatar.py`);
- CLI-команда `python -m reels_factory upload-photo`;
- запись/обновление профиля клиента через существующий `clients.register_client`;
- юнит-тесты (бесплатные, сеть замокана).

**НЕ делаем (осознанно вне объёма):**
- валидацию фото (ориентация, разрешение, формат) — по решению владельца;
- любые вызовы генерации видео (`/v3/videos`) — их в этой задаче нет вообще;
- код самого ТГ-бота;
- ретраи/очереди/лимиты.

## 3. Изменения в движке

### 3.1 `engine/src/reels_factory/avatar.py` — новая функция

```python
def upload_photo_asset(image_path, api_key=None, http=None) -> str:
    """Залить фото аватара в HeyGen /v3/assets, вернуть asset_id."""
```

Требования:
- `image_path` — путь к файлу; файла нет → `RuntimeError` с текстом
  `"файл фото не найден: <путь>"`;
- `api_key` — аргумент, иначе `env HEYGEN_API_KEY`; нет ключа →
  `RuntimeError` с тем же текстом-подсказкой, что в `HeyGenClient.generate`
  («установите env HEYGEN_API_KEY»);
- `http` — DI для тестов (дефолт `requests`), как во всех модулях движка;
- запрос: `POST UPLOAD_URL` (уже объявлен в module scope:
  `https://api.heygen.com/v3/assets`), заголовок `X-Api-Key`,
  `files={"file": (имя_файла, байты)}`, `timeout=120` — ровно та же схема,
  что в `HeyGenClient._upload_audio_v3` и `twin.TwinClient.upload_asset`;
- ответ: `resp.raise_for_status()`, затем `resp.json()["data"]["asset_id"]`;
  нет `asset_id` в ответе → `RuntimeError("HeyGen не вернул asset_id: <тело>")`;
- никакой обработки/конвертации картинки — байты уходят как есть.

Дублирование с `twin.upload_asset` допустимо (3 строки), НО если проще —
разрешается вынести общий приватный помощник; решение за исполнителем.
`twin.py` менять не обязательно.

### 3.2 `engine/src/reels_factory/__main__.py` — команда `upload-photo`

```
python -m reels_factory upload-photo --image <файл> --client <id>
       [--name <имя>] [--voice-id <vid>] [--from <base.yaml>] [--overwrite]
```

Поведение:
1. Команда обрабатывается ДО общего блока `load_config()` — как `clone-voice`
   (активный `factory/config.yaml` для неё не обязателен, см. п. 3).
2. `asset_id = upload_photo_asset(args.image)`.
3. Выбор базового конфига для профиля:
   - профиль `factory/clients/<id>.yaml` УЖЕ существует:
     - без `--overwrite` → ошибка
       `"клиент <id> уже есть — передай --overwrite, чтобы заменить фото"`,
       exit 1, ничего не загружать в HeyGen НЕ нужно проверять заранее —
       допустимо проверить существование профиля ДО загрузки (дешевле);
     - с `--overwrite` → база = сам существующий профиль (через
       `yaml.safe_load`, НЕ через `load_client` — чтобы не падать, если старый
       профиль стал невалиден): его `voice_id`, persona, product сохраняются;
   - профиля нет → база = `--from <путь>` либо дефолтный `factory/config.yaml`
     через `load_config`; конфига нет → понятная ошибка про
     `/reels-factory:setup`, exit 1.
4. `register_client(args.client, base, name=args.name, voice_id=args.voice_id,
   asset_id=asset_id, overwrite=True)` — photo-режим: `register_client` сам
   удалит `heygen_look_id` из базы и провалидирует записанный файл.
5. Вывод — JSON одной строкой (`ensure_ascii=False`), как у остальных команд:
   - успех, exit 0:
     `{"ok": true, "client": "<id>", "asset_id": "<...>", "mode": "photo",
       "path": "factory/clients/<id>.yaml"}`
   - любая ошибка (`ConfigError`, `RuntimeError`, HTTP): exit 1,
     `{"ok": false, "error": "<текст, обрезанный до 500 символов>"}`.

Замечания:
- `--client` обязателен: команда существует ради профиля; «просто получить
  asset_id без записи» — не наш кейс (бот всегда пишет профиль);
- невалидный id (`../x`, пустой) отбрасывает существующий `_safe_id` —
  специально ничего писать не нужно, но ошибка должна уходить в JSON, а не
  трейсбеком.

### 3.3 Что НЕ трогаем

`make`, `script*`, `pipeline.py`, `verify.py`, `twin.py`, скиллы. Скилл
`setup` можно позже перевести на эту команду — отдельной задачей.

## 4. Тесты

Все тесты бесплатные: сеть только мокается, ни один тест не вызывает
`/v3/videos`, ElevenLabs или рендер. Стиль — как в существующих
`engine/tests/test_avatar.py` / `test_cli.py` / `test_clients.py`
(фейковый `http` через DI, `tmp_path`, `monkeypatch`, имена тестов на русском).

### 4.1 Юнит: `upload_photo_asset` (в `tests/test_avatar.py`)

1. **Успех**: фейковый `http.post` возвращает
   `{"data": {"asset_id": "img_123"}}` → функция возвращает `"img_123"`;
   проверить собранный запрос: URL = `UPLOAD_URL`, заголовок
   `X-Api-Key` = переданный ключ, в `files` имя и байты исходного файла.
2. **Нет ключа**: `HEYGEN_API_KEY` очищен (`monkeypatch.delenv`), `api_key`
   не передан → `RuntimeError`, в тексте упоминается `HEYGEN_API_KEY`.
3. **Нет файла**: путь не существует → `RuntimeError` с путём в тексте,
   `http.post` НЕ вызывался.
4. **HTTP-ошибка**: фейковый ответ с `raise_for_status`, бросающим исключение
   (например 500) → исключение пробрасывается.
5. **Кривой ответ**: `{"data": {}}` → `RuntimeError` «не вернул asset_id».

### 4.2 CLI: `upload-photo` (в `tests/test_cli.py`)

Подготовка: `tmp_path` как cwd (`monkeypatch.chdir`), в нём валидный
`factory/config.yaml` (формат `avatar`, есть `voice_id`, `persona`,
`product`); `upload_photo_asset` замокан (`monkeypatch.setattr`), чтобы CLI-тесты
не зависели от HTTP-слоя. ВАЖНО: `config.FACTORY_DIR`/`clients.CLIENTS_DIR`
вычисляются от `Path.cwd()` на импорте — в тестах патчить константы модулей,
как это уже делается в существующих тестах реестра.

6. **Новый клиент**: `upload-photo --image p.jpg --client kaz1` →
   exit 0; создан `factory/clients/kaz1.yaml`; в нём
   `avatar.heygen_asset_id == "img_123"`, `heygen_look_id` отсутствует;
   `voice_id` унаследован из базового конфига; JSON-ответ содержит
   `"ok": true` и `"asset_id"`.
7. **Переопределение голоса**: с `--voice-id v_custom` → в профиле
   `voice_id == "v_custom"`.
8. **Повтор без `--overwrite`**: клиент существует → exit 1, JSON
   `"ok": false`, текст про `--overwrite`; файл профиля не изменился;
   замоканный upload НЕ вызывался.
9. **Повтор с `--overwrite`**: у существующего профиля свой
   `voice_id: v_old` и `heygen_look_id: look_old` → после команды
   `voice_id` сохранён (`v_old`), `heygen_asset_id` = новый,
   `heygen_look_id` удалён (photo-режим).
10. **Невалидный id**: `--client "../evil"` → exit 1, JSON `"ok": false`,
    файл вне `factory/clients/` НЕ создан.
11. **Нет базового конфига**: нет `factory/config.yaml` и нет `--from` (и
    профиля нет) → exit 1, в тексте упоминание setup.

### 4.3 Стык с реестром и `make` (бесплатно, генерация не стартует)

12. **`clients list`**: после теста 6 команда
    `python -m reels_factory clients list` показывает клиента с
    `"mode": "photo"` и правильным `asset_id` (юнит-уровень: можно напрямую
    `list_clients()`).
13. **Профиль подхватывается `make` и падает ДО платных шагов**: вызвать
    `make --client kaz1 --workdir empty_wd` на пустом workdir (нет
    `scenario.json`) → JSON с `"stage": "scenario"`, exit 1. Это доказывает:
    профиль прошёл `load_client`-валидацию и цепочка дошла до чтения сценария,
    остановившись раньше первого сетевого/платного вызова (TTS — стадия
    `voice`, до неё дело не дошло). Мокать ничего не нужно.

### 4.4 Регрессия

14. Полный прогон сьюта: `PYTHONPATH=src python -m pytest tests/ -q` —
    все существующие тесты остаются зелёными (эталон на 2026-07-24:
    265 passed; `test_ingest`/`test_llm` могут падать только из-за отсутствия
    yt-dlp/claude CLI в окружении — это не регрессия этой задачи).

### 4.5 Ручной live-смоук (опционально, тоже бесплатный)

Загрузка ассета в HeyGen не тарифицируется (платная — только генерация
видео, а её в задаче нет). При желании один раз вручную:

```
python -m reels_factory upload-photo --image <реальное фото> --client test_smoke
```

Проверить: exit 0, `asset_id` непустой, профиль создан. Профиль потом удалить
(`factory/clients/test_smoke.yaml`). В автотесты live-смоук НЕ включать.
`make` после этого НЕ запускать — он платный.

## 5. Критерии приёмки

- `upload-photo` с валидным фото и ключом создаёт/обновляет профиль клиента
  с `avatar.heygen_asset_id` за один вызов, вывод — машиночитаемый JSON;
- команда пригодна для вызова из ТГ-бота «как есть» (не требует интерактива,
  все ошибки — в JSON + exit-код);
- тесты 1–13 написаны и зелёные, сьют без регрессий;
- ни один автотест не делает реальных сетевых вызовов.
