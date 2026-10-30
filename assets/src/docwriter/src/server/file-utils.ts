// DocWriter's server/file-utils.ts: a file written whole, by the dashboard (as `os.replace` does).
import { writeFileSync } from './fs';

export const writeTextAtomic = (path: string, text: string): void => writeFileSync(path, text);
