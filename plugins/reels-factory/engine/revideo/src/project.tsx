import {Video, makeScene2D, Txt, Rect, Layout, Circle, Img, Audio, Gradient} from '@revideo/2d';
import {
  all, createRef, waitFor, makeProject, useTime,
  easeOutCubic, easeInOutSine, easeOutBack, easeOutQuad, easeInQuad, easeInOutQuad,
  tween, Reference,
} from '@revideo/core';
import tz from './tz.json';
import wordsFile from './words.json';
import './global.css';

const W = 1080, H = 1920;
const YELLOW = '#FFE500';
const FONT = (tz as any).brand?.font ?? 'Unbounded';
const DURATION = (tz as any).meta.duration;
const LANGUAGE = String((tz as any).meta?.language ?? 'ru').toLowerCase();
const COPY = LANGUAGE === 'kk' ? {
  personaBadge: 'А',
  formal: 'РЕСМИ ТҮРДЕ',
  actual: 'ШЫН МӘНІНДЕ',
  orderMatters: 'РЕТІ ШЕШЕДІ',
  subscribe: 'ЖАЗЫЛУ',
} : {
  personaBadge: 'Ч',
  formal: 'ФОРМАЛЬНО',
  actual: 'НА САМОМ ДЕЛЕ',
  orderMatters: 'ПОРЯДОК РЕШАЕТ',
  subscribe: 'ПОДПИСАТЬСЯ',
};
const MASTER_AUDIO = (tz as any).meta?.master_audio as string | undefined;
const SEGMENTS = (tz as any).segments ?? [];
const KEYWORDS: string[] = (tz as any).captions?.keywords ?? [];
const SFX = (tz as any).sfx ?? [];
const CAP_Y = 560, CAP_TOP = -640;
const CAP_40 = 195; // ~40% up from the bottom (0.4 * 1920 from bottom edge)

interface Word {start: number; end: number; text: string;}
const words: Word[] = (wordsFile as any).words;
const norm = (s: string) => s.normalize('NFKC').toLocaleLowerCase()
  .replace(/[^\p{L}\p{N}]/gu, '');
const isKw = (t: string) => KEYWORDS.some(k => norm(k) === norm(t));

// caption placement per time window
const capMode = (t: number): 'bottom' | 'top' | 'hidden' => {
  const seg = SEGMENTS.find((s: any) => t >= s.start && t < s.end);
  return (seg?.caption ?? 'bottom');
};

// premium gradient text fills
const whiteGrad = () => new Gradient({type: 'linear', from: [0, -70], to: [0, 70],
  stops: [{offset: 0, color: '#FFFFFF'}, {offset: 1, color: '#C9CCD6'}]});
const goldGrad = () => new Gradient({type: 'linear', from: [0, -70], to: [0, 70],
  stops: [{offset: 0, color: '#FFF27A'}, {offset: 0.5, color: YELLOW}, {offset: 1, color: '#FFB300'}]});
// solid dark backdrop (plate) for fullscreen graphic overlays
const darkPlate = () => new Gradient({type: 'linear', from: [0, -H / 2], to: [0, H / 2],
  stops: [{offset: 0, color: '#1E1B26'}, {offset: 1, color: '#0C0C10'}]});

/* ================= CAMERA ================= */
function* camera(v: Reference<Video>) {
  let t = 0;
  for (const seg of SEGMENTS) {
    if (seg.start > t) {yield* waitFor(seg.start - t); t = seg.start;}
    const D = seg.end - seg.start;
    const c = seg.camera || {type: 'hold'};
    switch (c.type) {
      case 'zoom_out': v().scale(c.from ?? 1.15); yield* v().scale(c.to ?? 1.0, D, easeOutCubic); break;
      case 'punch': v().scale(c.from ?? 1.12); yield* v().scale(c.to ?? 1.06, D, easeOutCubic); break;
      case 'push': yield* v().scale(c.to ?? 1.09, D, easeInOutSine); break;
      case 'snap_zoom': v().scale(1.0); yield* v().scale(c.to ?? 1.14, 0.18, easeOutBack); yield* waitFor(D - 0.18); break;
      case 'ken_burns': v().scale(1.0).position([0, 0]); yield* v().scale(1.09, D, easeInOutSine); break;
      case 'pulse': {
        const n = Math.max(1, Math.round(D / 0.85)), per = D / n;
        for (let i = 0; i < n; i++) {yield* v().scale(1.06, per * 0.35, easeOutQuad); yield* v().scale(1.0, per * 0.65, easeInOutSine);}
        break;
      }
      case 'shake_zoom': {
        const hold = Math.max(0, D - 0.5); yield* waitFor(hold);
        yield* v().scale(1.1, 0.12, easeOutQuad);
        for (let i = 0; i < 4; i++) {v().position([i % 2 ? 14 : -14, i % 2 ? -10 : 10]); yield* waitFor(0.045);}
        v().position([0, 0]); yield* v().scale(1.0, 0.2, easeOutQuad); break;
      }
      default: yield* waitFor(D);
    }
    t = seg.end;
  }
}

/* ================= CAPTIONS — neat phrase style ================= */
const segIndexAt = (t: number) => SEGMENTS.findIndex((s: any) => t >= s.start && t < s.end);
// group words into short phrase chunks.
// Rule: a chunk never crosses a segment boundary (so subtitles respect the same
// timeline the effects use, and never bleed onto a fullscreen/hidden segment).
function buildChunks(ws: Word[]) {
  const chunks: Word[][] = [];
  let cur: Word[] = [];
  let curSeg = -2;
  for (const w of ws) {
    const seg = segIndexAt(w.start);
    if (cur.length && seg !== curSeg) {chunks.push(cur); cur = [];} // break at segment boundary
    if (!cur.length) curSeg = seg;
    cur.push(w);
    const endsPunct = /[,.!?…]$/.test(w.text);
    if (cur.length >= 5 || (endsPunct && cur.length >= 3)) {chunks.push(cur); cur = [];}
  }
  if (cur.length) chunks.push(cur);
  return chunks;
}

function* captions(layer: Reference<Layout>) {
  const chunks = buildChunks(words);
  const CAP_FONT = 'Unbounded';
  const yPos = CAP_40; // ~40% from the bottom
  for (const ch of chunks) {
    const start = ch[0].start;
    const end = ch[ch.length - 1].end;
    const s0 = useTime();
    if (start > s0) yield* waitFor(start - s0);
    if (capMode(start) === 'hidden') {const r = end - useTime(); if (r > 0) yield* waitFor(r); continue;}
    // size the whole phrase so it fits ~90% width, then reveal words one by one
    const fullText = ch.map(w => w.text).join(' ').toUpperCase();
    let fs = 46; // small Unbounded
    const est = fullText.length * fs * 0.82; // Unbounded is wide
    if (est > W * 0.9) fs = Math.max(28, Math.floor(fs * (W * 0.9) / est));
    const cont = createRef<Layout>();
    layer().add(
      <Layout ref={cont} y={yPos} layout direction={'row'} gap={fs * 0.32} alignItems={'center'} zIndex={30} />,
    );
    for (let k = 0; k < ch.length; k++) {
      const w = ch[k];
      const now = useTime();
      if (w.start > now) yield* waitFor(w.start - now);
      const wref = createRef<Txt>();
      cont().add(
        <Txt ref={wref} text={w.text.toUpperCase()} fontFamily={CAP_FONT} fontWeight={700} fontSize={fs}
          fill={'rgba(255,255,255,0.95)'} letterSpacing={0.5}
          shadowColor={'rgba(0,0,0,0.6)'} shadowBlur={12} shadowOffset={[0, 3]}
          opacity={0} scale={0.85} />,
      );
      yield* all(wref().opacity(1, 0.06), wref().scale(1, 0.1, easeOutBack));
    }
    const rem = end - useTime(); if (rem > 0) yield* waitFor(rem);
    yield* cont().opacity(0, 0.1);
    cont().remove();
  }
}

/* ================= SFX ================= */
function* sfx(view: Layout) {
  let t = 0;
  for (const cue of SFX) {yield* waitFor(cue.t - t); view.add(<Audio src={`/${cue.sound}.wav`} play={true} />); t = cue.t;}
}

/* ================= b-roll: face-centered avatar bubble ================= */
function makeBubble(fxLayer: Layout, bubble: Reference<Layout>, cfg: any) {
  const R = 280, M = 44;
  const pos: Record<string, [number, number]> = {
    bottom_left: [-(W / 2 - R - M), H / 2 - R - M], bottom_right: [W / 2 - R - M, H / 2 - R - M],
    top_left: [-(W / 2 - R - M), -(H / 2 - R - M)], top_right: [W / 2 - R - M, -(H / 2 - R - M)],
  };
  const [bx, by] = pos[cfg.position] ?? pos.bottom_left;
  const face = cfg.face ?? {cx: 540, cy: 700, h: 320};
  const crop = face.h * (cfg.face_zoom ?? 3.1);
  const s = (2 * R) / crop;
  const vx = (W / 2 - face.cx) * s, vy = (H / 2 - face.cy) * s - (cfg.face_dy ?? 0);
  const square = cfg.shape === 'square';
  const frame = square
    ? <Rect size={2 * R + 18} radius={44} fill={'#FFF'} shadowColor={'rgba(0,0,0,0.5)'} shadowBlur={40} shadowOffset={[0, 16]} />
    : <Circle size={2 * R + 18} fill={'#FFF'} shadowColor={'rgba(0,0,0,0.5)'} shadowBlur={40} shadowOffset={[0, 16]} />;
  // play=true so the clip actually decodes/advances; cfg._t is the scene time at
  // the moment of creation, so it starts from the frame matching the audio -> in sync
  const clip = square
    ? <Rect size={2 * R} radius={34} clip><Video src={'/base.mp4'} time={cfg._t} play volume={0} size={[W * s, H * s]} x={vx} y={vy} /></Rect>
    : <Circle size={2 * R} clip><Video src={'/base.mp4'} time={cfg._t} play volume={0} size={[W * s, H * s]} x={vx} y={vy} /></Circle>;
  fxLayer.add(<Layout ref={bubble} x={bx} y={by} scale={0} zIndex={24}>{frame}{clip}</Layout>);
}

/* ================= EFFECTS ================= */
// A segment "covers" the face if its main visual is a fullscreen overlay.
const isCover = (s: any) =>
  !!s && (s.effect?.type === 'broll_bg_particles' || s.effect?.type === 'chart_bars' ||
    ['complexity_cloud', 'persona_card', 'value_layers', 'concept_nodes', 'sequence_flow']
      .includes(s.effect?.type) ||
    (s.effect?.type === 'broll' && s.effect?.style === 'fullscreen'));
const MIN_SHOT = 1.2; // seconds — no shot may flash shorter than this between two others

function* effects(fx: Reference<Layout>, base: Reference<Video>, flash: Reference<Rect>) {
  const plate = createRef<Rect>();
  for (let i = 0; i < SEGMENTS.length; i++) {
    const seg = SEGMENTS[i];
    const prev = SEGMENTS[i - 1], next = SEGMENTS[i + 1];
    const nowStart = useTime();
    if (seg.start > nowStart) yield* waitFor(seg.start - nowStart);
    const D = seg.end - seg.start;
    let used = 0;
    const use = function* (d: number) {used += d; yield* waitFor(Math.max(0, d));};

    // ---- flash-frame rule: bridge adjacent covering segments with one shared backdrop ----
    const cover = isCover(seg);
    const bridgedIn = cover && isCover(prev) && (seg.start - prev.end) < MIN_SHOT;
    const bridgedOut = cover && isCover(next) && (next.start - seg.end) < MIN_SHOT;
    if (cover && !bridgedIn) {
      fx().add(<Rect ref={plate} size={[W, H]} fill={darkPlate()} opacity={0} zIndex={12} />);
      yield* plate().opacity(1, 0.2); used += 0.2;
    }

    // transitions
    if (seg.transition_in === 'whip') {
      yield* base().position([-W * 0.5, 0], 0.1, easeInQuad); base().position([W * 0.5, 0]);
      yield* base().position([0, 0], 0.14, easeOutQuad); used += 0.24;
    } else if (seg.transition_in === 'zoom_blur') {
      const sc = base().scale().x;
      yield* base().scale(sc * 1.18, 0.1, easeOutQuad);
      yield* flash().opacity(0.35, 0.05); yield* flash().opacity(0, 0.14);
      yield* base().scale(sc, 0.1); used += 0.29;
    }

    const e = seg.effect || {type: 'none'};
    switch (e.type) {
      case 'broll': {
        if (e.style === 'fullscreen') {
          const br = createRef<Video>();
          fx().add(<Video ref={br} src={`/${e.src}`} time={e.offset ?? 0} play volume={0} size={[W, H]} opacity={0} zIndex={15} />);
          yield* br().opacity(1, 0.25); used += 0.25;
          if (e.bubble) {
            const bub = createRef<Layout>();
            makeBubble(fx(), bub, {...e.bubble, _t: useTime()});
            yield* bub().scale(1, 0.45, easeOutBack); used += 0.45;
            yield* use(Math.max(0, D - used - 0.3));
            yield* all(br().opacity(0, 0.25), bub().scale(0, 0.2, easeInQuad)); used += 0.3;
            bub().remove();
          } else {
            yield* use(Math.max(0, D - used - 0.25));
            yield* br().opacity(0, 0.25); used += 0.25;
          }
          br().remove();
        } else if (e.style === 'pip') {
          const holder = createRef<Layout>(); const cw = 820, ch = 1040;
          fx().add(
            <Layout ref={holder} y={H} scale={0.92} rotation={2} zIndex={20}>
              <Rect size={[cw + 16, ch + 16]} radius={48} fill={'#FFF'} shadowColor={'rgba(0,0,0,0.55)'} shadowBlur={60} shadowOffset={[0, 24]} />
              <Video src={`/${e.src}`} time={e.offset ?? 0} play volume={0} size={[cw, ch]} radius={40} />
            </Layout>);
          yield* all(holder().y(-160, 0.5, easeOutBack), holder().rotation(-2, 0.5, easeOutBack)); used += 0.5;
          yield* use(Math.max(0, D - used - 0.4));
          yield* all(holder().y(H, 0.4, easeInQuad)); used += 0.4; holder().remove();
        } else if (e.style === 'split') {
          // avatar stays fullscreen on top half; opaque b-roll covers bottom half
          const br = createRef<Layout>(); const half = H / 2;
          fx().add(
            <Layout ref={br} zIndex={16} opacity={0}>
              <Rect size={[W, half]} y={half / 2} clip>
                <Video src={`/${e.src}`} time={e.offset ?? 0} play volume={0} size={[W, H]} y={-200} />
              </Rect>
              <Rect size={[W, 10]} y={0} fill={YELLOW} shadowColor={'rgba(0,0,0,0.4)'} shadowBlur={10} />
            </Layout>);
          yield* br().opacity(1, 0.25); used += 0.25;
          yield* use(Math.max(0, D - used - 0.3));
          yield* br().opacity(0, 0.25); used += 0.25; br().remove();
        }
        break;
      }
      case 'emoji_pop_sequence': {
        const items = e.items as {word: string; img: string}[];
        const refs: Reference<Layout>[] = [];
        for (let k = 0; k < items.length; k++) {
          const it = items[k];
          const wd = words.find(w => norm(w.text) === norm(it.word) && w.start >= seg.start);
          const at = wd ? wd.start : seg.start + k * (D / items.length);
          yield* use(Math.max(0, at - (seg.start + used)));
          const em = createRef<Layout>(); const x = (k - 1) * 300;
          fx().add(
            <Layout ref={em} x={x} y={-640} scale={0} rotation={-8} zIndex={38}>
              <Img src={`/emoji/${it.img}.png`} size={190} shadowColor={'rgba(0,0,0,0.4)'} shadowBlur={24} shadowOffset={[0, 10]} />
            </Layout>);
          refs.push(em);
          yield* all(em().scale(1, 0.32, easeOutBack), em().rotation(0, 0.32, easeOutBack)); used += 0.32;
        }
        yield* use(Math.max(0, D - used - 0.3));
        yield* all(...refs.map(r => r().scale(0, 0.22, easeInQuad))); used += 0.3;
        refs.forEach(r => r().remove());
        break;
      }
      case 'broll_bg_particles': {
        const br = createRef<Video>(); const dim = createRef<Rect>();
        fx().add(<Video ref={br} src={`/${e.src}`} time={e.offset ?? 0} play volume={0} size={[W, H]} opacity={0} zIndex={15} />);
        fx().add(<Rect ref={dim} size={[W, H]} fill={'rgba(0,0,0,0.45)'} opacity={0} zIndex={16} />);
        yield* all(br().opacity(1, 0.25), dim().opacity(1, 0.25)); used += 0.25;
        const icons = e.icons as string[]; const refs: Reference<Layout>[] = [];
        const gap = Math.max(0.12, (D - used - 0.4) / icons.length);
        for (let k = 0; k < icons.length; k++) {
          const p = createRef<Layout>();
          const px = (k % 2 ? 1 : -1) * (110 + ((k * 67) % 300));
          const py = -420 + ((k * 130) % 900);
          fx().add(<Layout ref={p} x={px} y={py + 70} scale={0} opacity={0} zIndex={20}>
            <Img src={`/emoji/${icons[k]}.png`} size={120 + (k % 3) * 26} shadowColor={'rgba(0,0,0,0.45)'} shadowBlur={22} shadowOffset={[0, 8]} />
          </Layout>);
          refs.push(p);
          // pop in while drifting up
          yield* all(p().opacity(1, 0.15), p().scale(1, 0.18, easeOutBack), p().y(py, 0.18, easeOutQuad));
          used += 0.18;
          yield* use(Math.max(0, gap - 0.18));
        }
        yield* use(Math.max(0, D - used - 0.3));
        yield* all(br().opacity(0, 0.25), dim().opacity(0, 0.25), ...refs.map(r => r().opacity(0, 0.25))); used += 0.3;
        br().remove(); dim().remove(); refs.forEach(r => r().remove());
        break;
      }
      case 'complexity_cloud': {
        const group = createRef<Layout>();
        const title = createRef<Txt>();
        const resolution = createRef<Layout>();
        const items = ((e.items ?? []) as string[]).slice(0, 5);
        const chips: Reference<Layout>[] = [];
        fx().add(
          <Layout ref={group} zIndex={36}>
            <Txt ref={title} text={String(e.title ?? '').toUpperCase()} y={-650}
              width={900} textAlign={'center'} fontFamily={FONT} fontWeight={800}
              fontSize={48} fill={YELLOW} opacity={0} />
          </Layout>,
        );
        yield* title().opacity(1, 0.25); used += 0.25;
        const positions: [number, number, number][] = [
          [-230, -360, -4], [230, -170, 3], [-180, 40, -2],
          [210, 250, 4], [0, 420, 0],
        ];
        for (let k = 0; k < items.length; k++) {
          const chip = createRef<Layout>();
          const [x, y, rotation] = positions[k];
          group().add(
            <Layout ref={chip} x={x} y={y} rotation={rotation} opacity={0} scale={0.86}>
              <Rect layout padding={[26, 36]} radius={26}
                fill={'rgba(255,255,255,0.08)'} stroke={'rgba(255,255,255,0.22)'} lineWidth={2}>
                <Txt text={String(items[k]).toUpperCase()} fontFamily={FONT} fontWeight={700}
                  fontSize={35} fill={'#FFF'} />
              </Rect>
            </Layout>,
          );
          chips.push(chip);
          yield* all(chip().opacity(1, 0.22), chip().scale(1, 0.28, easeOutBack));
          used += 0.28;
        }
        yield* use(Math.max(0, Math.min(D * 0.48, D - 1.2) - used));
        yield* all(group().opacity(0, 0.3), group().scale(0.72, 0.3, easeInQuad));
        used += 0.3;
        fx().add(
          <Layout ref={resolution} scale={0.72} opacity={0} zIndex={38}>
            <Rect width={900} minHeight={500} layout direction={'column'} gap={34}
              alignItems={'center'} justifyContent={'center'} padding={70} radius={42}
              fill={'rgba(255,229,0,0.10)'} stroke={YELLOW} lineWidth={3}>
              <Txt text={'→'} fontFamily={FONT} fontWeight={800} fontSize={86} fill={YELLOW} />
              <Txt text={String(e.resolution ?? '').toUpperCase()} width={760} textAlign={'center'}
                fontFamily={FONT} fontWeight={800} fontSize={62} lineHeight={72} fill={'#FFF'} />
            </Rect>
          </Layout>,
        );
        yield* all(resolution().opacity(1, 0.4), resolution().scale(1, 0.5, easeOutBack));
        used += 0.5;
        yield* use(Math.max(0, D - used - 0.25));
        yield* resolution().opacity(0, 0.25); used += 0.25;
        group().remove(); resolution().remove();
        break;
      }
      case 'persona_card': {
        const panel = createRef<Layout>();
        const badge = createRef<Circle>();
        const rows = ((e.items ?? []) as string[]).slice(0, 4);
        const rowRefs: Reference<Layout>[] = [];
        fx().add(
          <Layout ref={panel} opacity={0} zIndex={36}>
            <Rect width={920} minHeight={1040} layout direction={'column'} gap={28}
              alignItems={'center'} padding={70} radius={48}
              fill={'rgba(255,229,0,0.07)'} stroke={'rgba(255,229,0,0.55)'} lineWidth={2}>
              <Circle ref={badge} size={160} fill={YELLOW} scale={0.68}>
                <Txt text={COPY.personaBadge} fontFamily={FONT} fontWeight={900} fontSize={70} fill={'#111'} />
              </Circle>
              <Txt text={String(e.title ?? '').toUpperCase()} width={760} textAlign={'center'}
                fontFamily={FONT} fontWeight={800} fontSize={46} fill={YELLOW} />
            </Rect>
          </Layout>,
        );
        yield* panel().opacity(1, 0.24); used += 0.24;
        yield* badge().scale(1, 0.38, easeOutBack); used += 0.38;
        const host = panel().children()[0] as Rect;
        for (let k = 0; k < rows.length; k++) {
          const row = createRef<Layout>();
          host.add(
            <Layout ref={row} width={780} minHeight={132} layout direction={'row'}
              gap={28} alignItems={'center'} opacity={0}>
              <Txt text={`${k + 1}`.padStart(2, '0')} fontFamily={FONT} fontWeight={800}
                fontSize={28} fill={YELLOW} />
              <Txt text={String(rows[k]).toUpperCase()} width={670} fontFamily={FONT}
                fontWeight={750} fontSize={42} lineHeight={50} fill={'#FFF'} />
            </Layout>,
          );
          rowRefs.push(row);
          yield* all(row().opacity(1, 0.22), row().y(0, 0.28, easeOutQuad));
          used += 0.28;
        }
        yield* use(Math.max(0, D - used - 0.25));
        yield* panel().opacity(0, 0.25); used += 0.25;
        panel().remove(); void rowRefs;
        break;
      }
      case 'value_layers': {
        const heading = createRef<Txt>();
        const offer = createRef<Layout>();
        const actual = createRef<Layout>();
        fx().add(
          <Txt ref={heading} text={String(e.title ?? '').toUpperCase()} y={-620}
            width={900} textAlign={'center'} fontFamily={FONT} fontWeight={800}
            fontSize={46} fill={YELLOW} opacity={0} zIndex={37} />,
        );
        fx().add(
          <Layout ref={offer} scale={0.72} opacity={0} zIndex={36}>
            <Rect width={900} minHeight={500} layout direction={'column'} gap={36}
              alignItems={'center'} justifyContent={'center'} padding={70} radius={42}
              fill={'rgba(255,255,255,0.06)'} stroke={'rgba(255,255,255,0.18)'} lineWidth={2}>
              <Txt text={COPY.formal} fontFamily={'Manrope'} fontWeight={800}
                fontSize={30} letterSpacing={6} fill={'rgba(255,255,255,0.55)'} />
              <Txt text={String(e.offer ?? '').toUpperCase()} width={760} textAlign={'center'}
                fontFamily={FONT} fontWeight={800} fontSize={64} lineHeight={74} fill={'#FFF'} />
            </Rect>
          </Layout>,
        );
        yield* all(heading().opacity(1, 0.25), offer().opacity(1, 0.36), offer().scale(1, 0.42, easeOutQuad));
        used += 0.42;
        yield* use(Math.max(0, Math.min(D * 0.46, D - 1.25) - used));
        yield* all(offer().opacity(0, 0.32), offer().scale(0.72, 0.32, easeInQuad));
        used += 0.32;
        fx().add(
          <Layout ref={actual} scale={1.28} opacity={0} zIndex={38}>
            <Rect width={900} minHeight={500} layout direction={'column'} gap={36}
              alignItems={'center'} justifyContent={'center'} padding={70} radius={42}
              fill={'rgba(255,229,0,0.10)'} stroke={YELLOW} lineWidth={3}>
              <Txt text={COPY.actual} fontFamily={'Manrope'} fontWeight={800}
                fontSize={30} letterSpacing={5} fill={YELLOW} />
              <Txt text={String(e.actual ?? '').toUpperCase()} width={760} textAlign={'center'}
                fontFamily={FONT} fontWeight={800} fontSize={64} lineHeight={74} fill={'#FFF'} />
            </Rect>
          </Layout>,
        );
        yield* all(actual().opacity(1, 0.38), actual().scale(1, 0.48, easeOutBack));
        used += 0.48;
        yield* use(Math.max(0, D - used - 0.25));
        yield* all(actual().opacity(0, 0.25), heading().opacity(0, 0.25)); used += 0.25;
        heading().remove(); offer().remove(); actual().remove();
        break;
      }
      case 'concept_nodes': {
        const hub = createRef<Layout>();
        const group = createRef<Layout>();
        const values = ((e.items ?? []) as string[]).slice(0, 3);
        const nodeRefs: Reference<Layout>[] = [];
        const lineRefs: Reference<Rect>[] = [];
        fx().add(<Layout ref={group} zIndex={36} />);
        group().add(
          <Layout ref={hub} opacity={0} scale={0.66}>
            <Rect width={500} minHeight={280} layout alignItems={'center'} justifyContent={'center'}
              padding={46} radius={140} fill={'rgba(255,229,0,0.10)'}
              stroke={YELLOW} lineWidth={3}>
              <Txt text={String(e.title ?? '').toUpperCase()} width={420} textAlign={'center'}
                fontFamily={FONT} fontWeight={800} fontSize={42} lineHeight={50} fill={'#FFF'} />
            </Rect>
          </Layout>,
        );
        yield* all(hub().opacity(1, 0.34), hub().scale(1, 0.46, easeOutBack)); used += 0.46;
        const positions: [number, number][] = [[0, -520], [-310, 510], [310, 510]];
        const rotations = [-90, 130, 50];
        for (let k = 0; k < values.length; k++) {
          const line = createRef<Rect>(); const node = createRef<Layout>();
          group().add(<Rect ref={line} width={0} height={4} x={0} y={0}
            rotation={rotations[k]} offsetX={-1} fill={YELLOW} opacity={0.65} />);
          group().add(
            <Layout ref={node} x={positions[k][0]} y={positions[k][1]} scale={0.7} opacity={0}>
              <Rect width={350} minHeight={160} layout alignItems={'center'} justifyContent={'center'}
                padding={30} radius={32} fill={'#171819'} stroke={'rgba(255,255,255,0.20)'} lineWidth={2}>
                <Txt text={String(values[k]).toUpperCase()} width={300} textAlign={'center'}
                  fontFamily={FONT} fontWeight={800} fontSize={42} fill={'#FFF'} />
              </Rect>
            </Layout>,
          );
          lineRefs.push(line); nodeRefs.push(node);
          yield* line().width(k === 0 ? 390 : 470, 0.22, easeOutQuad);
          yield* all(node().opacity(1, 0.22), node().scale(1, 0.3, easeOutBack));
          used += 0.52;
        }
        yield* use(Math.max(0, D - used - 0.25));
        yield* group().opacity(0, 0.25); used += 0.25;
        group().remove(); void lineRefs; void nodeRefs;
        break;
      }
      case 'sequence_flow': {
        const panel = createRef<Layout>();
        const heading = createRef<Txt>();
        const values = ((e.items ?? []) as string[]).slice(0, 4);
        const steps: Reference<Rect>[] = [];
        fx().add(
          <Layout ref={panel} zIndex={36} layout direction={'column'} gap={22} alignItems={'center'}>
            <Txt text={COPY.orderMatters} fontFamily={'Manrope'} fontWeight={800}
              fontSize={30} letterSpacing={6} fill={YELLOW} />
            <Txt ref={heading} text={String(e.title ?? '').toUpperCase()} width={900}
              textAlign={'center'} fontFamily={FONT} fontWeight={800}
              fontSize={56} lineHeight={66} fill={'#FFF'} opacity={0} />
          </Layout>,
        );
        yield* heading().opacity(1, 0.32); used += 0.32;
        for (let k = 0; k < values.length; k++) {
          const step = createRef<Rect>();
          panel().add(
            <Rect ref={step} width={840} minHeight={180} layout direction={'row'} gap={36}
              alignItems={'center'} padding={[34, 46]} radius={34}
              fill={'rgba(255,255,255,0.06)'} stroke={'rgba(255,255,255,0.16)'}
              lineWidth={2} opacity={0} scale={0.9}>
              <Circle size={94} fill={YELLOW}>
                <Txt text={`${k + 1}`.padStart(2, '0')} fontFamily={FONT}
                  fontWeight={900} fontSize={32} fill={'#111'} />
              </Circle>
              <Txt text={String(values[k]).toUpperCase()} width={620} fontFamily={FONT}
                fontWeight={800} fontSize={48} fill={'#FFF'} />
            </Rect>,
          );
          steps.push(step);
          yield* all(step().opacity(1, 0.22), step().scale(1, 0.32, easeOutBack));
          used += 0.32;
        }
        yield* use(Math.max(0, D - used - 0.25));
        yield* panel().opacity(0, 0.25); used += 0.25;
        panel().remove(); void steps;
        break;
      }
      case 'chart_bars': {
        const items = e.items as {t: number; label: string; v: number}[];
        const panel = createRef<Layout>();
        const bub = createRef<Layout>();
        fx().add(
          <Layout ref={panel} y={-40} opacity={0} zIndex={36} layout direction={'column'} gap={26} alignItems={'start'}>
            <Txt fontFamily={FONT} fontWeight={900} fontSize={52} fill={YELLOW}
              shadowColor={'rgba(0,0,0,0.6)'} shadowBlur={16}>{e.title}</Txt>
          </Layout>);
        if (e.bubble) {
          // Offline fallback for a failed HyperFrames render must preserve the
          // same canonical mixed composition: chart background + Avatar IV.
          makeBubble(fx(), bub, {...e.bubble, _t: useTime()});
          yield* all(
            panel().opacity(1, 0.25),
            bub().scale(1, 0.45, easeOutBack),
          );
          used += 0.45;
        } else {
          yield* panel().opacity(1, 0.25); used += 0.25;
        }
        const barRefs: Reference<Rect>[] = [];
        for (const it of items) {
          yield* use(Math.max(0, it.t - (seg.start + used)));
          const row = createRef<Layout>(); const bar = createRef<Rect>();
          panel().add(
            <Layout ref={row} layout direction={'column'} gap={8} opacity={0} alignItems={'start'}>
              <Txt fontFamily={FONT} fontWeight={800} fontSize={38} fill={'#FFF'}
                shadowColor={'rgba(0,0,0,0.6)'} shadowBlur={12}>{it.label}</Txt>
              <Rect ref={bar} width={0} height={44} radius={22} fill={goldGrad()}
                shadowColor={'rgba(0,0,0,0.4)'} shadowBlur={16} shadowOffset={[0, 6]} />
            </Layout>);
          barRefs.push(bar);
          yield* row().opacity(1, 0.15);
          yield* bar().width(120 + it.v * 640, 0.4, easeOutQuad); used += 0.55;
        }
        yield* use(Math.max(0, D - used - 0.3));
        if (e.bubble) {
          yield* all(
            panel().opacity(0, 0.3),
            bub().scale(0, 0.2, easeInQuad),
          );
          bub().remove();
        } else {
          yield* panel().opacity(0, 0.3);
        }
        used += 0.3;
        panel().remove();
        break;
      }
      case 'chat_bubble': {
        // light "message" bubble — low-intensity accent, sits below the face
        const b = createRef<Layout>();
        fx().add(
          <Layout ref={b} x={150} y={150} scale={0} rotation={-2} zIndex={38}>
            <Rect layout fill={'#FFFFFF'} radius={30} padding={[22, 36]}
              shadowColor={'rgba(0,0,0,0.35)'} shadowBlur={28} shadowOffset={[0, 12]}>
              <Txt fontFamily={'Manrope'} fontWeight={700} fontSize={46} fill={'#161616'}>{e.text}</Txt>
            </Rect>
          </Layout>);
        yield* all(b().scale(1.06, 0.28, easeOutBack), b().rotation(0, 0.28, easeOutBack));
        yield* b().scale(1.0, 0.1); used += 0.38;
        yield* use(Math.max(0, D - used - 0.25));
        yield* all(b().opacity(0, 0.2), b().scale(0.92, 0.2)); used += 0.25;
        b().remove();
        break;
      }
      case 'cta_endcard': {
        const btn = createRef<Layout>(); const finger = createRef<Layout>();
        fx().add(
          <Layout ref={btn} y={520} scale={0} zIndex={40}>
            <Rect layout fill={goldGrad()} radius={30} padding={[26, 54]} shadowColor={'rgba(0,0,0,0.5)'} shadowBlur={40} shadowOffset={[0, 16]}>
              <Txt fontFamily={FONT} fontWeight={900} fontSize={72} fill={'#161616'}>
                {String(e.button ?? COPY.subscribe).toLocaleUpperCase(
                  LANGUAGE === 'kk' ? 'kk-KZ' : 'ru-RU',
                )}
              </Txt>
            </Rect>
          </Layout>);
        yield* btn().scale(1.1, 0.3, easeOutBack); yield* btn().scale(1.0, 0.12); used += 0.42;
        const spL = createRef<Layout>(); const spR = createRef<Layout>();
        fx().add(<Layout ref={spL} x={-300} y={420} scale={0} zIndex={41}><Img src={'/emoji/sparkles.png'} size={120} /></Layout>);
        fx().add(<Layout ref={spR} x={300} y={620} scale={0} zIndex={41}><Img src={'/emoji/sparkles.png'} size={90} /></Layout>);
        yield* all(spL().scale(1, 0.3, easeOutBack), spR().scale(1, 0.3, easeOutBack)); used += 0.3;
        const pulses = Math.max(1, Math.floor((D - used) / 0.6));
        for (let i = 0; i < pulses; i++) {
          yield* all(btn().scale(1.05, 0.2, easeOutQuad), spL().rotation(12, 0.2), spR().rotation(-12, 0.2));
          yield* all(btn().scale(1.0, 0.25), spL().rotation(0, 0.25), spR().rotation(0, 0.25)); used += 0.45;
        }
        void finger;
        yield* use(Math.max(0, D - used));
        break;
      }
      default: yield* use(Math.max(0, D - used));
    }
    // remove the shared backdrop only when the covering group actually ends
    if (cover && !bridgedOut) {
      const r0 = seg.end - useTime();
      if (r0 > 0.25) yield* waitFor(r0 - 0.25);
      yield* plate().opacity(0, 0.25);
      plate().remove();
    }
    void used;
    // resync to absolute scene time so effects never drift
    const rem = seg.end - useTime();
    if (rem > 0) yield* waitFor(rem);
  }
}

/* ================= progress + watermark ================= */
function* progress(bar: Reference<Rect>) {bar().width(0); yield* bar().width(W, DURATION);}
function* watermark(wm: Reference<Txt>) {yield* waitFor((tz as any).brand.watermark_from ?? 2.0); yield* wm().opacity(0.72, 0.4);}

/* ================= SCENE ================= */
const scene = makeScene2D('reel', function* (view) {
  const base = createRef<Video>();
  const fx = createRef<Layout>();
  const capLayer = createRef<Layout>();
  const flash = createRef<Rect>();
  const bar = createRef<Rect>();
  const wm = createRef<Txt>();
  view.add(
    <>
      <Rect size={'100%'} fill={'#000'} zIndex={-1} />
      <Video ref={base} src={'/base.mp4'} size={[W, H]} play volume={MASTER_AUDIO ? 0 : 1} zIndex={0} />
      {MASTER_AUDIO ? <Audio src={`/${MASTER_AUDIO}`} play={true} /> : null}
      <Layout ref={fx} size={'100%'} zIndex={20} />
      <Layout ref={capLayer} size={'100%'} zIndex={30} />
      <Rect ref={flash} size={'100%'} fill={'#FFF'} opacity={0} zIndex={50} />
      <Rect ref={bar} height={12} width={0} fill={YELLOW} offsetX={-1} x={-W / 2} y={H / 2 - 6} zIndex={60} />
      <Txt ref={wm} text={(tz as any).brand.watermark} fontFamily={FONT} fontWeight={800} fontSize={32}
        fill={'#FFF'} opacity={0} y={-H / 2 + 70} zIndex={60} shadowColor={'rgba(0,0,0,0.6)'} shadowBlur={12} />
    </>,
  );
  yield* all(camera(base), effects(fx, base, flash), captions(capLayer), sfx(view), progress(bar), watermark(wm), waitFor(DURATION));
});

export default makeProject({scenes: [scene], settings: {shared: {size: {x: W, y: H}}}});
