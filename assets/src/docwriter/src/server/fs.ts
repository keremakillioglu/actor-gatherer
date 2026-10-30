// Node's fs, the four calls DocWriter's document tools make (mcp-doc-tools.ts), done by the dashboard.
import { ask } from './sync';

export function existsSync(path: string): boolean {
	try { return ask('exists', { path }).exists === true; } catch { return false; }
}
export function readFileSync(path: string, _encoding?: string): string {
	return ask('read', { path }).text;
}
export function writeFileSync(path: string, content: string, _encoding?: string): void {
	ask('write', { path, text: String(content) });
}
export function mkdirSync(path: string, _opts?: unknown): void {
	ask('mkdir', { path });
}
