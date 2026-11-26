/**
 * Theme preference model — the single source of truth for theming.
 *
 * Preference: 'light' | 'dark' | 'system' (persisted under THEME_KEY).
 * Resolved theme: 'light' | 'dark' (written to <html data-theme>).
 * Default with no saved preference is 'system'; when the OS reports no dark
 * preference the result is Light, the product's primary theme.
 *
 * index.html contains a tiny inline copy of `resolveTheme` that runs before the
 * first paint so the page never flashes the wrong theme.
 */
export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_KEY = 'aap_theme';
export const THEME_META_COLOR: Record<ResolvedTheme, string> = { light: '#FAFAFA', dark: '#121214' };

export function readThemePreference(storage: Pick<Storage, 'getItem'> | null): ThemePreference {
  try {
    const value = storage?.getItem(THEME_KEY);
    return value === 'light' || value === 'dark' || value === 'system' ? value : 'system';
  } catch {
    return 'system';
  }
}

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light';
  return preference;
}

export function applyTheme(root: HTMLElement, resolved: ResolvedTheme, doc: Document = document): void {
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  doc.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_META_COLOR[resolved]);
}

export const DARK_QUERY = '(prefers-color-scheme: dark)';
