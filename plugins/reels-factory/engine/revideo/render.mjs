import {renderVideo} from '@revideo/renderer';

console.log('Rendering...');
const file = await renderVideo({
  projectFile: './src/project.tsx',
  settings: {
    outFile: 'reel_revideo_v7.mp4',
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
console.log(`Rendered video to ${file}`);
