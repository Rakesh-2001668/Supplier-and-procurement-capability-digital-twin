'use client';

import { Monitor, Moon, Sun } from 'lucide-react';
import { useEffect, useSyncExternalStore } from 'react';
import { applyTheme, readChoice, saveChoice, THEME_EVENT, ThemeChoice } from '@/lib/theme';

const OPTIONS: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'Match my computer', Icon: Monitor },
];

// The stored choice lives in localStorage: read it as an external store (the server renders "system").
function subscribe(onChange: () => void) {
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener('storage', onChange);          // another tab changed it
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener('storage', onChange);
  };
}

/** Light / dark / system switch (a radio group: arrow keys move between the three). */
export default function ThemeToggle({ showLabels = true }: { showLabels?: boolean }) {
  const choice = useSyncExternalStore(subscribe, readChoice, () => 'system' as ThemeChoice);

  // "Match my computer" follows the operating system while the page is open; another tab's change applies here too.
  useEffect(() => {
    applyTheme(choice, false);
    if (choice !== 'system') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const follow = () => applyTheme('system');
    media.addEventListener('change', follow);
    return () => media.removeEventListener('change', follow);
  }, [choice]);

  const onKey = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const to = (index + step + OPTIONS.length) % OPTIONS.length;
    saveChoice(OPTIONS[to].value);
    (e.currentTarget.parentElement?.children[to] as HTMLElement | undefined)?.focus();
  };

  return (
    <div role="radiogroup" aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-full border border-line bg-surface-2 p-0.5">
      {OPTIONS.map(({ value, label, Icon }, i) => {
        const on = choice === value;
        return (
          <button key={value} type="button" role="radio" aria-checked={on} aria-label={label} title={label} tabIndex={on ? 0 : -1}
            onClick={() => saveChoice(value)} onKeyDown={(e) => onKey(e, i)}
            className={`flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
              on ? 'bg-surface text-ink shadow-card' : 'text-ink-3 hover:text-ink'}`}>
            <Icon size={14} aria-hidden />
            {showLabels && value !== 'system' && <span aria-hidden className="hidden 2xl:inline">{label}</span>}
          </button>
        );
      })}
    </div>
  );
}
