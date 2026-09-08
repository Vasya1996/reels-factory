#!/bin/sh
# Черновики прогонов живут две недели.
#
# Запускается хуком SessionStart и печатает, что убрал: у SessionStart stdout
# уходит в контекст, так что отчёт видит и Клод, и пользователь.
# Ничего не блокирует — при любой ошибке сессия продолжается.
#
# Ручной прогон без удаления:  sh prune-work.sh --dry-run

RETENTION_DAYS=${RETENTION_DAYS:-14}

# Хранилища, которые не устаревают по возрасту:
#   avatar_cache        — переиспользуемые рендеры HeyGen, каждый стоил денег
#   bot                 — профили пользователей бота: session.json и input с фото и голосом
#   elevenlabs-tts-sts  — голоса
#   plan-previews       — превью планов
KEEP="avatar_cache bot elevenlabs-tts-sts plan-previews"

# Рабочая папка: сперва переменная окружения, затем прод, затем эта машина.
WORK=${REELS_WORK:-}
[ -n "$WORK" ] || { [ -d /root/reels-workspace/work ] && WORK=/root/reels-workspace/work; }
[ -n "$WORK" ] || { [ -d "$HOME/Videos/Reels/work" ] && WORK="$HOME/Videos/Reels/work"; }
[ -n "$WORK" ] || exit 0

DRY=0
[ "$1" = "--dry-run" ] && DRY=1

# Чистятся два уровня: разовые папки прогонов в корне work и задания внутри
# work/jobs. Сама папка jobs не удаляется никогда — только её содержимое.
count=0
for dir in "$WORK"/*/ "$WORK"/jobs/*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")

    skip=0
    for k in $KEEP; do
        [ "$name" = "$k" ] && skip=1
    done
    [ "$dir" = "$WORK/jobs/" ] && skip=1
    [ "$skip" = 1 ] && continue

    # Возраст считается по самому свежему файлу внутри: у папки, в которую
    # недавно писали, mtime самого каталога может остаться старым.
    fresh=$(find "$dir" -type f -newermt "-${RETENTION_DAYS} days" -print -quit 2>/dev/null)
    [ -n "$fresh" ] && continue

    if [ "$DRY" = 1 ]; then
        echo "убрал бы: $name"
    else
        rm -rf "$dir" && echo "убрано: $name"
    fi
    count=$((count + 1))
done

[ "$count" -gt 0 ] && echo "черновиков старше ${RETENTION_DAYS} дней: ${count} (${WORK})"
exit 0
