// DocWriter's server/ydoc-persistence.ts: the dashboard keeps a document's history, not the page; a file the agent
// creates is made empty and opened.
export const tabHasPersistedUpdates = (_tabId: string): boolean => false;
