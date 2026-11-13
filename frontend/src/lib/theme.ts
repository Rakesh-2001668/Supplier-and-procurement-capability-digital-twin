// Light / dark theme. The choice ("light", "dark" or "system") is kept in localStorage per browser; "system" follows the
// operating system and changes with it. <html data-theme> carries the resolved theme; globals.css and theme-dark.css read it.

export type ThemeChoice = 'light' | 'dark' | 'system';
export const THEME_KEY = 'pic-theme';
/** Window event fired after the choice changes in this tab (the toggle listens to it and to `storage` for other tabs). */
export const THEME_EVENT = 'pic-theme-change';

/** Runs in <head> before the first paint, so a dark-theme user never sees a white flash. Keep it small and dependency-free. */
export const THEME_BOOT_SCRIPT = `(function(){try{var c=localStorage.getItem('${THEME_KEY}');var d=c==='dark'||((!c||c==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=d?'dark':'light';}catch(e){document.documentElement.dataset.theme='light';}})();`;

export function readChoice(): ThemeChoice {
  try {
    const c = localStorage.getItem(THEME_KEY);
    return c === 'light' || c === 'dark' ? c : 'system';
  } catch {
    return 'system';
  }
}

export function resolve(choice: ThemeChoice): 'light' | 'dark' {
  if (choice !== 'system') return choice;
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Applies a theme with a short cross-fade (skipped when the user prefers reduced motion). */
export function applyTheme(choice: ThemeChoice, animate = true) {
  const root = document.documentElement;
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (animate && !calm) {
    root.classList.add('theme-transition');
    window.setTimeout(() => root.classList.remove('theme-transition'), 320);
  }
  root.dataset.theme = resolve(choice);
}

export function saveChoice(choice: ThemeChoice) {
  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // storage blocked (private window): the theme still changes on this page
  }
  applyTheme(choice);
  window.dispatchEvent(new Event(THEME_EVENT));
}
