// Convierte videos/<name>.mp4 a docs/media/<name>.gif:
//   ffmpeg 2 pasadas (palettegen/paletteuse) a 10 fps, ancho por demo
//   (820px hero / 760px resto, como los <img> del README), recorte de
//   esperas muertas (timeline) + gifsicle -O3. Objetivo <5MB.
// Extrae frames de verificación en work/<name>/.
//
// Uso: node convert.mjs <name> [fps]

import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  statSync,
  unlinkSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { FFMPEG, VIDEOS_DIR } from "./record.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GIFS_DIR = resolve(__dirname, "../../docs/media");
const WORK_DIR = resolve(__dirname, "work");
const GIFSICLE = resolve(__dirname, "../gifsicle/gifsicle.exe");

// Ancho del GIF final por demo (el README usa 820px para el hero, 760px resto).
const WIDTHS = { hero: 820, apply: 760, achievements: 760, "variant-gen": 760, imports: 760, history: 760 };

const name = process.argv[2];
let fps = Number(process.argv[3] || 10);
if (!name) {
  console.error("uso: node convert.mjs <name> [fps]");
  process.exit(1);
}
const width = WIDTHS[name] || 760;

const mp4 = resolve(VIDEOS_DIR, `${name}.mp4`);
const timelineFile = resolve(VIDEOS_DIR, `${name}.timeline.json`);
if (!existsSync(mp4)) {
  console.error(`falta ${mp4}`);
  process.exit(1);
}

// Ventanas de corte en segundos (desde el timeline), por demo.
function cutWindows(marks) {
  const t = (n) => marks.find((m) => m.name === n)?.t;
  const out = [];
  if (name === "apply" || name === "hero") {
    const gc = t("gen_click");
    const gr = t("gen_result");
    const rc = t("render_click");
    const rd = t("render_done");
    if (gc != null && gr != null && gr - gc > 3) out.push([gc + 1.5, gr - 0.8]);
    if (rc != null && rd != null && rd - rc > 3) out.push([rc + 1.5, rd - 0.8]);
  }
  if (name === "variant-gen" || name === "history" || name === "imports") {
    const vc = t("gen_click");
    const vr = t("gen_result");
    if (vc != null && vr != null && vr - vc > 3) out.push([vc + 1.5, vr - 0.8]);
  }
  return out;
}

function buildSelect(cuts) {
  const expr = cuts.map(([a, b]) => `between(t,${a},${b})`).join("+");
  return expr ? `select='not(${expr})'` : null;
}

function runFfmpeg(args) {
  const r = spawnSync(FFMPEG, ["-y", ...args], { stdio: "inherit" });
  if (r.status !== 0) {
    console.error(`ffmpeg falló (exit ${r.status})`);
    process.exit(1);
  }
}

function convert(fpsNow) {
  const marks = existsSync(timelineFile)
    ? JSON.parse(readFileSync(timelineFile, "utf8"))
    : [];
  const cuts = cutWindows(marks);
  const sel = buildSelect(cuts);
  const vf = `fps=${fpsNow},scale=${width}:-1:flags=lanczos${sel ? `,${sel}` : ""},setpts=N/FRAME_RATE/TB`;
  const pal = resolve(WORK_DIR, `${name}-palette.png`);
  const gif = resolve(WORK_DIR, `${name}.gif`);
  const final = resolve(GIFS_DIR, `${name}.gif`);
  mkdirSync(WORK_DIR, { recursive: true });
  console.log(
    `[convert] ${name}: fps=${fpsNow} cortes=${
      cuts.length ? cuts.map((c) => `[${c[0]}-${c[1]}s]`).join(" ") : "ninguno"
    }`,
  );
  runFfmpeg(["-i", mp4, "-vf", `${vf},palettegen`, "-an", pal]);
  runFfmpeg([
    "-i",
    mp4,
    "-i",
    pal,
    "-lavfi",
    `[0:v]${vf}[vid];[vid][1:v]paletteuse`,
    "-loop",
    "0",
    gif,
  ]);
  const rgif = spawnSync(GIFSICLE, ["-O3", "-l", "-o", gif, gif], {
    stdio: "inherit",
  });
  if (rgif.status !== 0) {
    console.error("gifsicle falló");
    process.exit(1);
  }
  return { gif, final, cuts };
}

let { gif, final } = convert(fps);
let sizeMb = statSync(gif).size / (1024 * 1024);
if (sizeMb > 5 && fps > 6) {
  console.warn(
    `[convert] ${sizeMb.toFixed(1)}MB > 5MB, reintento a ${fps - 2} fps`,
  );
  ({ gif } = convert((fps -= 2)));
  sizeMb = statSync(gif).size / (1024 * 1024);
}

copyFileSync(gif, final);
unlinkSync(gif);
console.log(`[convert] OK: ${final} (${sizeMb.toFixed(1)}MB, ${fps}fps)`);

// Frames de verificación (~0.5/s del GIF final) para revisión visual.
const framesDir = resolve(WORK_DIR, name);
mkdirSync(framesDir, { recursive: true });
spawnSync(FFMPEG, ["-y", "-i", final, "-vf", "fps=0.5", `${framesDir}\\frame-%02d.png`], {
  stdio: "ignore",
});
console.log(`[convert] frames de verificación en ${framesDir}/`);
