// DocWriter's server/workspace-path.ts: a workspace-relative path made absolute, never out of the folder (the
// dashboard checks again, links and all, when it is read or written).
import { resolve } from './path';
import { WORKSPACE_ROOT } from './document-files';

export function resolveWorkspacePath(relPath: string): string {
	const abs = resolve(WORKSPACE_ROOT, relPath);
	if (abs !== WORKSPACE_ROOT && !abs.startsWith(WORKSPACE_ROOT + '/')) throw new Error(`${relPath} is outside the workspace`);
	return abs;
}
