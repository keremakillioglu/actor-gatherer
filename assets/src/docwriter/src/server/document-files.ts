// DocWriter's server/document-files.ts, its workspace being this DocWriter's folder (state.ts's config.root).
import { join } from './path';

export let WORKSPACE_ROOT = '';
export let DOCWRITER_DIR = '';
export let AGENT_SCRATCH_DIR = '';

export function setRoot(root: string): void {
	WORKSPACE_ROOT = root;
	DOCWRITER_DIR = join(root, '.docwriter');
	AGENT_SCRATCH_DIR = join(DOCWRITER_DIR, 'agent', 'scratch');
}

export function isValidTabId(id: string): boolean {
	if (!id || id.length > 512) return false;
	if (id.startsWith('/') || id.startsWith('\\')) return false;
	if (id.includes('\0')) return false;
	for (const seg of id.split('/')) if (seg === '..' || seg === '.' || seg === '') return false;
	return true;
}

const BINARY_EXTENSIONS = new Set(['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp', 'tif', 'tiff',
	'zip', 'gz', 'tar', 'docx', 'xlsx', 'pptx', 'mp3', 'mp4', 'mov', 'wav']);
export function isBinaryTabPath(tabId: string): boolean {
	const base = tabId.split('/').pop() || '';
	const i = base.lastIndexOf('.');
	return i > 0 && BINARY_EXTENSIONS.has(base.slice(i + 1).toLowerCase());
}

export const tabFile = (tabId: string): string => join(WORKSPACE_ROOT, tabId);

export function isAgentScratchPath(path: string): boolean {
	return path === AGENT_SCRATCH_DIR || path.startsWith(AGENT_SCRATCH_DIR + '/');
}
