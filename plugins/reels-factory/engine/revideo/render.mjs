import {renderVideo} from '@revideo/renderer';
import fs from 'node:fs';
import path from 'node:path';

// ВАЖНО: рендерим всегда в ./output внутри модуля. Revideo резолвит ассеты
// (аудио видео-тегов) как <outDir>/../public — если отдать outDir во внешнюю
// папку воркдира, public/ не найдётся и итоговый ролик остаётся БЕЗ ЗВУКА
// (ffprobe тихо падает в лог). Внешний путь (env RF_OUTFILE) получает копию.
const outAbs = process.env.RF_OUTFILE ? path.resolve(process.env.RF_OUTFILE) : null;

console.log('Rendering ->', outAbs ?? path.resolve('./output/reel.mp4'));
const file = await renderVideo({
  projectFile: './src/project.tsx',
  settings: {
    outFile: 'reel.mp4',
    outDir: './output',
    logProgress: true,
    puppeteer: {
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--use-gl=swiftshader',
        '--disable-features=IsolateOrigins,site-per-process',
      ],
    },
  },
});
if (outAbs) {
  fs.mkdirSync(path.dirname(outAbs), {recursive: true});
  fs.copyFileSync(path.resolve(file ?? './output/reel.mp4'), outAbs);
}
console.log(`Rendered video to ${outAbs ?? file}`);
