import { mount } from 'svelte';
import Preview from './Preview.svelte';
import { installLive, type Bus } from './bus';

// its live notices from the DocWriter page that shows it (a frame of it) or opened it (a window)
const from = (w: Window | null): Bus | null => { try { return (w && w !== window && (w as any).__dwBus) || null; } catch { return null; } };
installLive(from(parent) ?? from(opener));

mount(Preview, { target: document.getElementById('app')! });
