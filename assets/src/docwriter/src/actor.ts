// The actor DocWriter's agent is (state.ts's config), as the dashboard page around this frame sees it: its status,
// whether its turn is over, what it asks -- the page posts it here each time it changes (page.html's DocWriter
// panel), as it has it for its own list and views.
export interface Actor {
	status?: string;            // running / asking / idle / background / closed / error
	turn_over?: boolean;
	asking?: { call: string; harness?: string; questions?: Array<{ question: string; options?: Array<{ label: string }> }> } | null;
	failing?: { text?: string } | null;
	stopped?: { kind: string } | null;
	session?: { session_id?: string; terminal?: boolean } | null;
	name?: string | null;
}

let actor: Actor | null = null;
let theme: string | null = new URLSearchParams(location.search).get('theme');   // the dashboard's, as it opened this page
const listeners = new Set<() => void>();
const themeListeners = new Set<(theme: string) => void>();

addEventListener('message', (ev) => {
	if (ev.origin !== location.origin || ev.source !== parent || ev.data?.kind !== 'ag-actor') return;
	actor = ev.data.actor ?? null;
	for (const l of [...listeners]) l();
	if (typeof ev.data.theme === 'string' && ev.data.theme !== theme) {    // the dashboard's light or dark, changed
		theme = ev.data.theme;
		for (const l of [...themeListeners]) l(theme!);
	}
});

/** The dashboard's theme, light or dark (null: not known). */
export const dashboardTheme = (): string | null => theme;

/** Called with the dashboard's theme, light or dark, each time it changes. */
export function onTheme(l: (theme: string) => void): void {
	themeListeners.add(l);
}
if (parent !== window) parent.postMessage({ kind: 'ag-actor?' }, location.origin);

export const current = (): Actor | null => actor;

/** Called on each change of the actor; the returned function stops it. */
export function onActor(l: () => void): () => void {
	listeners.add(l);
	return () => listeners.delete(l);
}
