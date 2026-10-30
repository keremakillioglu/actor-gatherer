// Node's AsyncLocalStorage, for DocWriter's per-render scope. The page runs one tool call at a time, so the store
// set by `run` is the one in force until its work is done.
export class AsyncLocalStorage<T> {
	private store: T | undefined;
	getStore(): T | undefined {
		return this.store;
	}
	run<R>(store: T, fn: () => R): R {
		const prev = this.store;
		this.store = store;
		let r: R;
		try { r = fn(); } catch (e) { this.store = prev; throw e; }
		if (r instanceof Promise) return r.finally(() => { this.store = prev; }) as R;
		this.store = prev;
		return r;
	}
}
