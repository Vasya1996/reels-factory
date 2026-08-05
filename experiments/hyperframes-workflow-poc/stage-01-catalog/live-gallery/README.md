# Stage 01.2 Live Gallery

Галерея показывает ровно 161 существующий catalog item из `inventory/items.json`: upstream blocks/components, local blocks, approved layouts и approved transitions.

## Команды

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/build-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/capture-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/validate-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/serve-live-gallery.mjs
```

Server слушает только `http://127.0.0.1:4173/`.

Preview pages лежат в `previews/<safe-catalog-id>/index.html`, thumbnails сняты локально из этих pages, contact sheets лежат в `contact-sheets/`.
