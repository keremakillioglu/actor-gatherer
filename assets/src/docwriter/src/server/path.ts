// Node's path, POSIX, as much of it as DocWriter's server code here uses.
function normalize(p: string): string {
	const abs = p.startsWith('/');
	const out: string[] = [];
	for (const seg of p.split('/')) {
		if (!seg || seg === '.') continue;
		if (seg === '..') { if (out.length && out[out.length - 1] !== '..') out.pop(); else if (!abs) out.push('..'); continue; }
		out.push(seg);
	}
	return (abs ? '/' : '') + out.join('/') || (abs ? '/' : '.');
}
export const isAbsolute = (p: string): boolean => p.startsWith('/');
export const join = (...parts: string[]): string => normalize(parts.filter(Boolean).join('/'));
export function resolve(...parts: string[]): string {
	let p = '';
	for (const part of parts) p = isAbsolute(part) ? part : p ? `${p}/${part}` : part;
	return normalize(p);
}
export function dirname(p: string): string {
	const n = normalize(p);
	const i = n.lastIndexOf('/');
	return i < 0 ? '.' : i === 0 ? '/' : n.slice(0, i);
}
export const basename = (p: string): string => normalize(p).split('/').pop() || '';
export function relative(from: string, to: string): string {
	const a = normalize(from).split('/').filter(Boolean), b = normalize(to).split('/').filter(Boolean);
	let i = 0;
	while (i < a.length && i < b.length && a[i] === b[i]) i++;
	return [...a.slice(i).map(() => '..'), ...b.slice(i)].join('/');
}
export const sep = '/';
export default { isAbsolute, join, resolve, dirname, basename, relative, sep };
