// DocWriter's server/runtime-state.ts: the rules, as the page last had them (state.ts).
import { meta } from '../state';

export const getRules = () => meta.rules as any[];
