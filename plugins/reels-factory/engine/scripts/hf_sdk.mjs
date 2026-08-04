// Мост к их редактору композиций: @hyperframes/sdk.
//
// Разбор HTML и правку композиции движок держит готовыми — «headless,
// framework-neutral composition editing engine for agents and custom editors»
// (packages/sdk/package.json:4). Сессия без адаптеров и есть наш режим:
// «Headless (agents): omit both — SDK is a stateless transform + serializer»
// (packages/sdk/src/session.ts:851-852). Своего разборщика HTML у нас поэтому
// больше нет.
//
// Процесс живёт всю сборку и говорит построчным JSON: открыть композицию —
// прочитать её элементы — применить правки — записать результат. Один запуск
// node на сборку вместо запуска на блок.
//
// Протокол (по строке на сообщение):
//   {"id":1,"cmd":"open","name":"g13","path":"…/g13.html"}      -> {"ok":true}
//   {"id":2,"cmd":"elements","name":"g13"}                      -> {"ok":true,"elements":[…]}
//   {"id":3,"cmd":"dispatch","name":"g13","ops":[EditOp,…]}     -> {"ok":true}
//   {"id":4,"cmd":"save","name":"g13","path":"…/copy.html"}     -> {"ok":true,"bytes":N}
//   {"id":5,"cmd":"close","name":"g13"}                         -> {"ok":true}
// Ошибка: {"ok":false,"error":"…"}.
//
// Файлами, а не текстом: блок каталога весит под полмегабайта, и гонять его
// через канал по два раза на карточку дороже, чем прочитать с диска.
import { openComposition } from "@hyperframes/sdk";
import { parseHTML } from "linkedom";
import { readFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

const sessions = new Map();

/** Собственный текст каждого элемента — только его текстовые узлы.
 *
 * Их снимок отдаёт поле `text`, но оно смотрит «сквозь» единственного потомка
 * (`packages/sdk/src/engine/model.ts:337-345`): у `<span><i></i>СЛОВО</span>`
 * текстом числится пустая полоска подсветки, а слово теряется. В нашем
 * каталоге акцентное слово устроено ровно так, поэтому текст читаем с их же
 * разметки их же разборщиком — linkedom, зависимость их SDK. Метки
 * `data-hf-id` проставляет сам SDK (`parsers/src/hfIds.ts:5`), по ним и
 * сходятся два взгляда на один документ.
 */
function ownTexts(comp) {
  const { document } = parseHTML(comp.serialize());
  const map = new Map();
  for (const element of document.querySelectorAll("[data-hf-id]")) {
    let text = "";
    element.childNodes.forEach((node) => {
      if (node.nodeType === 3) text += node.nodeValue ?? "";
      else if (node.nodeType === 1 && node.tagName === "BR") text += "\n";
    });
    map.set(element.getAttribute("data-hf-id"), text);
  }
  return map;
}

/** Плоский список элементов в порядке документа: у каждого свои дети и место. */
function flatten(comp) {
  const texts = ownTexts(comp);
  const out = [];
  const walk = (element, parent, index) => {
    const self = out.length;
    out.push({
      hfid: element.scopedId || element.id,
      tag: element.tag,
      classes: [...element.classNames],
      attrs: { ...element.attributes },
      text: texts.get(element.id) ?? "",
      start: element.start,
      duration: element.duration,
      trackIndex: element.trackIndex,
      anims: [...element.animationIds],
      parent,
      index,
      children: [],
    });
    element.children.forEach((child, position) => {
      out[self].children.push(out.length);
      walk(child, self, position);
    });
  };
  comp.getRootElements().forEach((root, position) => walk(root, null, position));
  return out;
}

function need(name) {
  const session = sessions.get(name);
  if (!session) throw new Error(`композиция ${name} не открыта`);
  return session;
}

async function handle(message) {
  switch (message.cmd) {
    case "open": {
      const html = readFileSync(message.path, "utf8");
      // history:false — стек отмены нам не нужен, а он держит копию документа
      // на каждую правку: на блоке в полмегабайта это заметная память.
      sessions.set(message.name, await openComposition(html, { history: false }));
      return { ok: true };
    }
    case "elements":
      return { ok: true, elements: flatten(need(message.name)) };
    case "dispatch": {
      const comp = need(message.name);
      // Пачкой: их движок сворачивает правки одной транзакцией.
      comp.batch(() => {
        for (const op of message.ops) comp.dispatch(op);
      });
      return { ok: true };
    }
    case "save": {
      const html = need(message.name).serialize();
      writeFileSync(message.path, html, "utf8");
      return { ok: true, bytes: html.length };
    }
    case "close":
      need(message.name).dispose();
      sessions.delete(message.name);
      return { ok: true };
    // Кусок чужого файла целиком, разметкой: так подключается их компонент
    // субтитров — «paste its contents into your composition»
    // (docs/catalog/components/caption-highlight.mdx). Через сессию SDK это не
    // достать: снимок отдаёт разбор, а не исходную разметку, — поэтому файл
    // читается их же разборщиком напрямую.
    case "extract": {
      const { document } = parseHTML(readFileSync(message.path, "utf8"));
      const found = message.all
        ? [...document.querySelectorAll(message.selector)]
        : [document.querySelector(message.selector)].filter(Boolean);
      return {
        ok: true,
        found: found.map((el) => ({ outer: el.outerHTML, text: el.textContent })),
      };
    }
    default:
      throw new Error(`неизвестная команда ${message.cmd}`);
  }
}

const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
  if (!line.trim()) continue;
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(error) }) + "\n");
    continue;
  }
  let answer;
  try {
    answer = await handle(request);
  } catch (error) {
    answer = { ok: false, error: error?.message ?? String(error) };
  }
  answer.id = request.id;
  process.stdout.write(JSON.stringify(answer) + "\n");
}
