#!/usr/bin/env bash
# Сборка эталонного ролика (то, что было согласовано визуально).
# Это НЕ продовый рендер, а воспроизводимый образец: по нему сверяется результат
# после интеграции в пайплайн.
#
#   AVATAR=avatar.mp4 VOICE=voice.mp3 WORK=work/ ./build_reference.sh out.mp4
#
# Ожидает в $WORK: series1.mp4..series3.mp4 (b-roll серии), zoom_expr.txt,
# flash_expr.txt, caps.ass (из camera_plan.py), arialbd.ttf.
set -e

AVATAR="${AVATAR:?укажи AVATAR=путь к видео с аватаром}"
VOICE="${VOICE:?укажи VOICE=путь к мастер-аудио}"
WORK="${WORK:-work}"
OUT="${1:-reference.mp4}"

Z=$(cat "$WORK/zoom_expr.txt")
FL=$(cat "$WORK/flash_expr.txt")

# фильтр subtitles на Windows ломается о "C:" в пути — работаем из каталога с .ass и шрифтом
cd "$WORK"

ffmpeg -y -v error -stats \
  -i "$AVATAR" \
  -i series1.mp4 -i series2.mp4 -i series3.mp4 \
  -i "$VOICE" \
  -filter_complex "
[0:v]scale=1620:2880:flags=lanczos,zoompan=z='$Z':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=25,eq=brightness='$FL':eval=frame[av];
[1:v]setpts=PTS-STARTPTS+8.30/TB[s1];
[2:v]setpts=PTS-STARTPTS+16.84/TB[s2];
[3:v]setpts=PTS-STARTPTS+23.14/TB[s3];
[av][s1]overlay=0:0:enable='between(t,8.30,12.10)'[o1];
[o1][s2]overlay=0:0:enable='between(t,16.84,20.64)'[o2];
[o2][s3]overlay=0:0:enable='between(t,23.14,26.22)'[o3];
[o3]subtitles=caps.ass:fontsdir=.,format=yuv420p[v]" \
  -map "[v]" -map 4:a \
  -c:v libx264 -crf 18 -preset medium -r 25 \
  -c:a aac -b:a 192k -movflags +faststart -shortest \
  "$OUT"

echo "OK -> $OUT"

# --- как собирается одна серия из двух b-roll планов (переход ВНУТРИ серии) ---
# GRADE подгоняет сток под тёплый свет съёмки, FIT кропит в вертикаль 1080x1920.
#
# GRADE="eq=brightness=0.015:contrast=1.03:saturation=1.06,colorbalance=rs=0.03:bs=-0.03"
# FIT="fps=25,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
# ffmpeg -y -i clipA.mp4 -i clipB.mp4 -filter_complex "
#   [0:v]trim=start=1.0:duration=2.21,setpts=PTS-STARTPTS,$FIT,$GRADE[a];
#   [1:v]trim=start=1.5:duration=1.77,setpts=PTS-STARTPTS,$FIT,$GRADE[b];
#   [a][b]xfade=transition=smoothleft:duration=0.18:offset=2.03,format=yuv420p[v]" \
#   -map "[v]" -an -c:v libx264 -crf 16 series1.mp4
#
# smoothleft = whip pan (база серии), fadewhite = вспышка (только кульминация).
