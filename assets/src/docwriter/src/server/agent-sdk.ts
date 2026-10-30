// The Claude Agent SDK's two calls DocWriter's document tools are declared with: each tool kept as declared, for
// tools.ts to offer and run (the dashboard's MCP server offers them to the actor).
export interface ToolDef {
	name: string;
	description: string;
	inputSchema: Record<string, unknown>;      // zod's raw shape
	handler: (args: any, extra?: unknown) => Promise<{ content: Array<{ type: string; text: string }>; isError?: boolean }>;
}
export function tool(name: string, description: string, inputSchema: Record<string, unknown>, handler: ToolDef['handler']): ToolDef {
	return { name, description, inputSchema, handler };
}
export function createSdkMcpServer(options: unknown): unknown {
	return options;
}
