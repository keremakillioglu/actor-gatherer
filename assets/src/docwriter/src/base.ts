// Where this DocWriter is served, /docwriter/w/<key> (index.html sets it): what the dashboard knows it by -- its
// folder, its actor -- and every request of its page goes under.
export const base: string = (globalThis as { __dwBase?: string }).__dwBase ?? '';
