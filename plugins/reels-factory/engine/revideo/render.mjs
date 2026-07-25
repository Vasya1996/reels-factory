import {renderVideo} from '@revideo/renderer';
import fs from 'node:fs';
import path from 'node:path';

// Код и node_modules общие, но project/src/public/output принадлежат одной job.
// Revideo резолвит ассеты как <outDir>/../public, поэтому RF_RENDER_DIR должен
// быть <job>/revideo/output, а RF_PROJECT_FILE — <job>/revideo/src/project.tsx.
const outAbs = process.env.RF_OUTFILE ? path.resolve(process.env.RF_OUTFILE) : null;
const projectFile = process.env.RF_PROJECT_FILE
  ? path.resolve(process.env.RF_PROJECT_FILE)
  : path.resolve('./src/project.tsx');
const renderDir = process.env.RF_RENDER_DIR
  ? path.resolve(process.env.RF_RENDER_DIR)
  : path.resolve('./output');

console.log('Rendering ->', outAbs ?? path.join(renderDir, 'reel.mp4'));
const file = await renderVideo({
  projectFile,
  settings: {
    outFile: 'reel.mp4',
    outDir: renderDir,
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
  fs.copyFileSync(path.resolve(file ?? path.join(renderDir, 'reel.mp4')), outAbs);
}
console.log(`Rendered video to ${outAbs ?? file}`);
