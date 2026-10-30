// DocWriter's server/db.ts: its SQLite database is the dashboard's to keep (docwriter.py); what server code the page
// runs reads nothing from it -- a custom reviewer comes from the page's own list (render.ts).
const none = { all: () => [], get: () => undefined, run: () => ({ changes: 0 }) };
export const getDb = (): any => ({ prepare: () => none, exec: () => undefined, transaction: (fn: any) => fn });
