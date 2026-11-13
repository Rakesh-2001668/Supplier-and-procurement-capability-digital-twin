#!/usr/bin/env node
/**
 * Generates src/app/theme-dark.css: the dark-theme colours for the Tailwind colour classes the screens already use.
 *
 * Most screens were written with fixed light classes (bg-white, text-slate-900, border-slate-200, bg-emerald-50 …). Rather
 * than adding a `dark:` twin to every class in every file, this script scans src/ for the colour classes in use and writes
 * one override per class that applies only while <html data-theme="dark">. The rules are unlayered, so they win over
 * Tailwind's utilities layer without !important.
 *
 * Mapping, per property:
 *   neutral greys   surfaces become dark slate tiers, dark text becomes light, light borders become dark borders
 *   colour tints    50–300 backgrounds and borders become a tint of the colour over the dark surface; 600–950 text lightens
 *   solid colours   (buttons, badges, charts: 400–700 backgrounds) stay as they are
 * Subtrees marked `.theme-fixed` (the sidebar, the twin screens with their own dark design) are left untouched.
 *
 * New components should use the theme tokens instead (bg-surface, text-ink, border-line …, see globals.css); rerun this
 * script after adding fixed colour classes:  node scripts/gen-dark-theme.mjs   (CI checks the file is current: --check)
 */
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'src');
const OUT = join(SRC, 'app', 'theme-dark.css');

// ---------------------------------------------------------------- palette (Tailwind v4 defaults, oklch)
const PALETTE = {};
for (const m of readFileSync(join(ROOT, 'node_modules', 'tailwindcss', 'theme.css'), 'utf8').matchAll(/--color-([a-z]+)-(\d{2,3}):\s*(oklch\([^)]*\))/g)) {
  (PALETTE[m[1]] ??= {})[m[2]] = m[3];
}
const NEUTRAL = new Set(['slate', 'gray', 'zinc', 'neutral', 'stone']);
const FAMILIES = Object.keys(PALETTE).sort();

// Dark tiers (slate-tinted) shared with the tokens in globals.css.
const D = { canvas: '#0b1120', surface: '#111a2e', s2: '#152036', s3: '#1c2840', s4: '#24314a', s5: '#2f3c57', s6: '#3a4762' };

const NEUTRAL_MAP = {
  bg: { white: D.surface, 50: D.s2, 100: D.s3, 200: D.s4, 300: D.s5, 400: '#46536d', 700: D.s6, 800: '#334155', 900: '#2a3650', 950: '#1e293b' },
  text: { black: '#f8fafc', 950: '#f8fafc', 900: '#f1f5f9', 800: '#e2e8f0', 700: '#cbd5e1', 600: '#aab6c8', 500: '#8b98ad' },
  border: { white: D.s4, 50: D.s3, 100: '#1f2a42', 200: D.s4, 300: '#33415c', 400: '#475569' },
  placeholder: { 300: '#4b5871', 400: '#64748b', 500: '#76849b' },
};

const tint = (family, pct) => `color-mix(in oklab, ${PALETTE[family]['500']} ${pct}%, ${D.surface})`;
const COLOUR_MAP = {
  bg: { 50: (f) => tint(f, 11), 100: (f) => tint(f, 17), 200: (f) => tint(f, 26), 300: (f) => tint(f, 36) },
  text: { 600: (f) => PALETTE[f]['400'], 700: (f) => PALETTE[f]['300'], 800: (f) => PALETTE[f]['200'], 900: (f) => PALETTE[f]['200'], 950: (f) => PALETTE[f]['100'] },
  border: { 50: (f) => tint(f, 14), 100: (f) => tint(f, 18), 200: (f) => tint(f, 28), 300: (f) => tint(f, 40) },
};

// ---------------------------------------------------------------- arbitrary hex colours (bg-[#F4F6FB] …)
function hexToOklch(hex) {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return { L, C: Math.hypot(A, B), H: ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360 };
}
const oklch = (L, C, H) => `oklch(${(L * 100).toFixed(1)}% ${C.toFixed(3)} ${H.toFixed(1)})`;

function mapHex(prop, hex) {
  const { L, C, H } = hexToOklch(hex);
  const neutral = C < 0.03;
  if (prop === 'text') {
    if (L >= 0.55) return null;                                    // already light enough on a dark surface
    return neutral ? (L < 0.3 ? '#f1f5f9' : '#cbd5e1') : oklch(0.78, Math.min(C, 0.14), H);
  }
  if (prop === 'bg') {
    if (L < 0.9) return null;                                      // solid colours and dark surfaces stay
    return neutral ? (L > 0.97 ? D.surface : D.canvas) : `color-mix(in oklab, ${oklch(0.6, C * 3, H)} 14%, ${D.surface})`;
  }
  if (prop === 'border') {
    if (L < 0.85) return null;
    return neutral ? D.s4 : `color-mix(in oklab, ${oklch(0.6, C * 3, H)} 28%, ${D.surface})`;
  }
  return null;
}

// ---------------------------------------------------------------- class scanning
const PROPS = {
  bg: { kind: 'bg', decl: (v) => `background-color: ${v}` },
  text: { kind: 'text', decl: (v) => `color: ${v}` },
  border: { kind: 'border', decl: (v) => `border-color: ${v}` },
  'border-t': { kind: 'border', decl: (v) => `border-top-color: ${v}` },
  'border-b': { kind: 'border', decl: (v) => `border-bottom-color: ${v}` },
  'border-l': { kind: 'border', decl: (v) => `border-left-color: ${v}` },
  'border-r': { kind: 'border', decl: (v) => `border-right-color: ${v}` },
  'border-x': { kind: 'border', decl: (v) => `border-left-color: ${v}; border-right-color: ${v}` },
  'border-y': { kind: 'border', decl: (v) => `border-top-color: ${v}; border-bottom-color: ${v}` },
  divide: { kind: 'border', decl: (v) => `border-color: ${v}`, child: true },
  ring: { kind: 'border', decl: (v) => `--tw-ring-color: ${v}` },
  outline: { kind: 'border', decl: (v) => `outline-color: ${v}` },
  placeholder: { kind: 'placeholder', decl: (v) => `color: ${v}`, pseudo: '::placeholder' },
  // Gradient stops: Tailwind reads these variables when it paints the gradient, so overriding them recolours it.
  from: { kind: 'bg', decl: (v) => `--tw-gradient-from: ${v}` },
  via: { kind: 'bg', decl: (v) => `--tw-gradient-via: ${v}` },
  to: { kind: 'bg', decl: (v) => `--tw-gradient-to: ${v}` },
};
const VARIANTS = {
  hover: ':hover', focus: ':focus', 'focus-visible': ':focus-visible', 'focus-within': ':focus-within', active: ':active',
  disabled: ':disabled', odd: ':nth-child(odd)', even: ':nth-child(even)', first: ':first-child', last: ':last-child',
  checked: ':checked', open: '[open]', placeholder: '::placeholder',
};
const GROUP_VARIANTS = { 'group-hover': '.group:hover ', 'group-focus-within': '.group:focus-within ' };

const PROP_NAMES = Object.keys(PROPS).sort((a, b) => b.length - a.length).map((p) => p.replace('-', '\\-')).join('|');
const CLASS_RE = new RegExp(
  `(?<![\\w\\-:/\\[])((?:[a-z\\-]+:)*)(${PROP_NAMES})-(?:(white|black)|(${FAMILIES.join('|')})-(\\d{2,3})|\\[(#[0-9a-fA-F]{3,8})\\])(?:/(\\d{1,3}))?(?![\\w\\-\\[])`,
  'g',
);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|jsx?)$/.test(name)) out.push(p);
  }
  return out;
}

const escapeClass = (c) => c.replace(/([:/\[\]#.%(),!])/g, '\\$1');
const withAlpha = (v, alpha) => (alpha ? `color-mix(in oklab, ${v} ${alpha}%, transparent)` : v);

function darkValue(prop, kind, special, family, shade, hex) {
  if (hex) return mapHex(kind, hex);
  if (special) return NEUTRAL_MAP[kind]?.[special] ?? null;
  if (!PALETTE[family]?.[shade]) return null;
  if (NEUTRAL.has(family)) return NEUTRAL_MAP[kind]?.[shade] ?? null;
  const fn = COLOUR_MAP[kind]?.[shade];
  return fn ? fn(family) : null;
}

const rules = new Map();
for (const file of walk(SRC)) {
  const text = readFileSync(file, 'utf8');
  for (const m of text.matchAll(CLASS_RE)) {
    const [whole, variantText, prop, special, family, shade, hex, alpha] = m;
    const variants = variantText ? variantText.slice(0, -1).split(':') : [];
    if (variants.some((v) => !(v in VARIANTS) && !(v in GROUP_VARIANTS))) continue;   // responsive, dark:, aria-… : left alone
    const spec = PROPS[prop];
    const value = darkValue(prop, spec.kind, special, family, shade, hex);
    if (!value) continue;
    let selector = `.${escapeClass(whole)}`;
    let prefix = '';
    let pseudoElement = spec.pseudo ?? '';                    // ::placeholder must come after the :not() below
    for (const v of variants) {
      if (VARIANTS[v]?.startsWith('::')) pseudoElement = VARIANTS[v];
      else if (v in VARIANTS) selector += VARIANTS[v];
      else prefix = GROUP_VARIANTS[v];
    }
    // :where() keeps the exemption from adding specificity; variants (hover, focus) still outrank the plain class.
    const rule = spec.child
      ? `${selector} > :not(:last-child):not(:where(.theme-fixed, .theme-fixed *) > *)`
      : `${selector}:not(:where(.theme-fixed, .theme-fixed *))${pseudoElement}`;
    rules.set(whole, `:root[data-theme="dark"] ${prefix}${rule} { ${spec.decl(withAlpha(value, alpha))}; }`);
  }
}

const body = [...rules.keys()].sort().map((k) => rules.get(k)).join('\n');
const css = `/* GENERATED by scripts/gen-dark-theme.mjs from the colour classes in src/. Do not edit; rerun the script. */\n${body}\n`;

if (process.argv.includes('--check')) {
  const current = (() => { try { return readFileSync(OUT, 'utf8'); } catch { return ''; } })();
  if (current.replace(/\r\n/g, '\n') !== css) {
    console.error('src/app/theme-dark.css is out of date: run  node scripts/gen-dark-theme.mjs');
    process.exit(1);
  }
  console.log(`theme-dark.css is current (${rules.size} rules)`);
} else {
  writeFileSync(OUT, css);
  console.log(`wrote ${OUT} (${rules.size} rules)`);
}
