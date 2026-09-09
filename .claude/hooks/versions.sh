#!/bin/sh
# Паспорт версий в начале сессии.
#
# Три числа живут порознь и расходятся молча: пин, на котором идёт рендер;
# клон, по которому сверяется библиотекарь; и то, что вышло у них в npm.
# Разбор, построенный на свежей цитате из клона, даёт не тот результат на
# старом пине — и это видно только по кадрам, после рендера.
#
# Запускается хуком SessionStart: его stdout уходит в контекст, так что
# расхождение видит и Клод, и Вася — до первого решения, а не после.
# Ничего не блокирует: при любой ошибке сессия продолжается.
#
# Ручной прогон: sh .claude/hooks/versions.sh
# Кэш версии из npm — рядом, в .npm-latest: «версия дата».

CLONE=${HYPERFRAMES_REF:-/c/Users/123/projects/hyperframes-ref}
[ -d "$CLONE" ] || CLONE="C:/Users/123/projects/hyperframes-ref"

PIN=$(grep -o '_HF_VERSION = "[^"]*"' \
    plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py 2>/dev/null \
    | head -1 | cut -d'"' -f2)
SDK=$(grep -o '"@hyperframes/sdk": "[^"]*"' \
    plugins/reels-factory/engine/package.json 2>/dev/null | cut -d'"' -f4)

printf 'HyperFrames: пин %s' "${PIN:-?}"
[ -n "$SDK" ] && printf ', sdk %s' "$SDK"

if [ -d "$CLONE/.git" ]; then
    # Возраст клона считаем по дате коммита: клон, не двигавшийся неделю,
    # цитирует не то, что у них сейчас.
    when=$(git -C "$CLONE" log -1 --format=%cd --date=short 2>/dev/null)
    days=$(( ( $(date +%s) - $(git -C "$CLONE" log -1 --format=%ct 2>/dev/null || date +%s) ) / 86400 ))
    behind=$(git -C "$CLONE" rev-list --count HEAD..origin/main 2>/dev/null)
    printf ', клон %s' "${when:-?}"
    [ "$days" -gt 0 ] 2>/dev/null && printf ' (%s дн. назад)' "$days"
    [ -n "$behind" ] && [ "$behind" != "0" ] && printf ', отстаёт на %s коммитов' "$behind"
else
    printf ', клон не найден (%s)' "$CLONE"
fi

# npm — единственное, что стоит сети, и стоит дорого: `npm view` держит около
# двадцати секунд. Ждать этого на старте сессии нельзя, поэтому печатаем из
# кэша, а обновляем его в фоне — число приезжает к следующей сессии. Версия
# суточной давности отвечает на вопрос «насколько мы отстали» ничуть не хуже.
CACHE=$(dirname "$0")/.npm-latest
if [ -f "$CACHE" ]; then
    LATEST=$(cut -d' ' -f1 "$CACHE" 2>/dev/null)
    WHEN=$(cut -d' ' -f2 "$CACHE" 2>/dev/null)
    [ -n "$LATEST" ] && printf ', в npm %s' "$LATEST"
    [ -n "$WHEN" ] && [ "$WHEN" != "$(date +%F)" ] && printf ' (на %s)' "$WHEN"
fi
printf '\n'

# Фоновое обновление кэша, не чаще раза в сутки. Сессию не задерживает.
if [ ! -f "$CACHE" ] || [ "$(cut -d' ' -f2 "$CACHE" 2>/dev/null)" != "$(date +%F)" ]; then
    ( v=$(npm view hyperframes version 2>/dev/null | tr -d '\r\n')
      [ -n "$v" ] && printf '%s %s\n' "$v" "$(date +%F)" > "$CACHE" ) >/dev/null 2>&1 &
fi

CC=$(claude --version 2>/dev/null | head -1)
[ -n "$CC" ] && printf 'Claude Code: %s\n' "$CC"

MAP=.claude/doc-map/claude-code.md
if [ -f "$MAP" ]; then
    stamp=$(grep -o 'Сгенерирована [0-9-]*' "$MAP" 2>/dev/null | head -1 | cut -d' ' -f2)
    [ -n "$stamp" ] && printf 'Карта доков: %s\n' "$stamp"
fi

exit 0
