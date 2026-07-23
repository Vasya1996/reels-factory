import {renderVideo} from '@revideo/renderer';
import path from 'node:path';

// Output path is set by the pipeline via env (RF_OUTFILE = absolute .mp4 path);
// falls back to ./output/reel.mp4 for standalone runs.
const outAbs = process.env.RF_OUTFILE
  ? path.resolve(process.env.RF_OUTFILE)
  : path.resolve('./output/reel.mp4');
const outDir = path.dirname(outAbs);
const outFile = path.basename(outAbs);

console.log('Rendering ->', outAbs);
const file = await renderVideo({
  projectFile: './src/project.tsx',
  settings: {
    outFile,
    outDir,
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
console.log(`Rendered video to ${file}`);
