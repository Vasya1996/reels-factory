# Live gallery audit

## Summary

- Cards total: 161
- PASS previews: 142
- FAIL previews: 19
- Contact sheets: 9
- Localized remote dependencies: 146
- Harness fixtures: 30

## Contact Sheet Review

- contact-sheets/sheet-01.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-02.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-03.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-04.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-05.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-06.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-07.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-08.jpg: 20 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.
- contact-sheets/sheet-09.jpg: 1 thumbnails physically opened/reviewed; PASS thumbnails are real local captures, FAIL thumbnails are red-bordered and documented.

## Manual Browser Check

- Main page opened at `http://127.0.0.1:4173/`.
- Cards visible: 161.
- Modal Play/Pause/Restart/Escape unload checked for upstream block, upstream component, local block, approved layout, approved transition.
- Search `avatar`: 6 cards.
- Filter `source=upstream`: 138 cards.
- Filter `kind=component`: 25 cards.
- Filter `live status=FAIL`: 19 cards.

## Failures

### upstream:block:code-3d-extrude

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Cannot read properties of undefined (reading 'WebGLRenderer')

### upstream:block:code-particle-assemble

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Cannot read properties of undefined (reading 'WebGLRenderer')

### upstream:block:code-shader-dissolve

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Cannot read properties of undefined (reading 'WebGLRenderer')

### upstream:block:ios26-liquid-glass

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FDRACOLoader.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FGLTFLoader.js
- pageerror: THREE is not defined

### upstream:block:liquid-glass-context-menu

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdnjs.cloudflare.com%2Fajax%2Flibs%2Fthree.js%2Fr128%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:liquid-glass-media-controls

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdnjs.cloudflare.com%2Fajax%2Flibs%2Fthree.js%2Fr128%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:liquid-glass-notification

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdnjs.cloudflare.com%2Fajax%2Flibs%2Fthree.js%2Fr128%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:liquid-glass-widgets

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdnjs.cloudflare.com%2Fajax%2Flibs%2Fthree.js%2Fr128%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:macos-tahoe-liquid-glass

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FDRACOLoader.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FGLTFLoader.js
- pageerror: THREE is not defined

### upstream:block:spain-map

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fd3%407%2Fdist%2Fd3.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Ftopojson-client%403.1.0%2Fdist%2Ftopojson-client.min.js
- console: Fetch API cannot load about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fes-atlas%400.6.0%2Fes%2Fautonomous_regions.json. URL scheme "about" is not supported.
- pageerror: Failed to fetch

### upstream:block:us-map

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fd3%407%2Fdist%2Fd3.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Ftopojson-client%403.1.0%2Fdist%2Ftopojson-client.min.js
- console: Fetch API cannot load about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fus-atlas%403%2Fstates-10m.json. URL scheme "about" is not supported.
- pageerror: Failed to fetch

### upstream:block:us-map-bubble

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fd3%407%2Fdist%2Fd3.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Ftopojson-client%403.1.0%2Fdist%2Ftopojson-client.min.js
- pageerror: d3 is not defined

### upstream:block:us-map-flow

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fd3%407%2Fdist%2Fd3.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Ftopojson-client%403.1.0%2Fdist%2Ftopojson-client.min.js
- pageerror: d3 is not defined

### upstream:block:vfx-iphone-device

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FDRACOLoader.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Floaders%2FGLTFLoader.js
- pageerror: THREE is not defined

### upstream:block:vfx-liquid-background

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:vfx-liquid-glass

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fshaders%2FCopyShader.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fshaders%2FLuminosityHighPassShader.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fpostprocessing%2FEffectComposer.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fpostprocessing%2FRenderPass.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fpostprocessing%2FShaderPass.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fexamples%2Fjs%2Fpostprocessing%2FUnrealBloomPass.js
- pageerror: THREE is not defined

### upstream:block:vfx-portal

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:vfx-shatter

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fthree%400.147.0%2Fbuild%2Fthree.min.js
- pageerror: THREE is not defined

### upstream:block:world-map

- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Fd3%407%2Fdist%2Fd3.min.js
- pageerror: Missing local runtime dependency: about:blank#remote-dependency-not-localized:https%3A%2F%2Fcdn.jsdelivr.net%2Fnpm%2Ftopojson-client%403.1.0%2Fdist%2Ftopojson-client.min.js
- pageerror: d3 is not defined

