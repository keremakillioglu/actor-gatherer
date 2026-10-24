// A chat view of your own, as an example: the conversation alone -- the user's messages and the
// assistant's answers, as bubbles, the answers' markdown rendered -- without tool calls, reasoning or
// system messages. To use it, copy it to <home>/dashboard/views/ (~/.ag/dashboard/views/) and reload
// the dashboard: "Conversation" joins the switch in the Chat tab. See "chat views" in page.html.
(() => {
  const { el, markdown, clock } = agDashboard;
  const style = document.createElement("style");
  style.textContent = `
    .bubbles { display: flex; flex-direction: column; gap: 10px; padding: 12px 4px; }
    .bubbles .b { max-width: 78%; padding: 8px 12px; border-radius: 12px; overflow-wrap: anywhere; font-size: 13px; line-height: 1.5; }
    .bubbles .b.user { align-self: flex-end; background: var(--selected); white-space: pre-wrap; border-bottom-right-radius: 4px; }
    .bubbles .b.agent { align-self: flex-start; background: var(--wash); border-bottom-left-radius: 4px; }
    .bubbles .b.agent > :first-child { margin-top: 0; } .bubbles .b.agent > :last-child { margin-bottom: 0; }
    .bubbles .b.pending { opacity: .7; }
    .bubbles .t { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .bubbles .b.user .t { text-align: right; }`;
  document.head.append(style);
  agDashboard.chatView({
    id: "conversation",
    name: "Conversation",
    description: "The user's messages and the assistant's answers alone, as bubbles.",
    feed: "history",            // the gatherer's events: {row_id, name, text, at, ...}
    frame: "",
    render({ data }) {
      const said = [...data.items, ...data.pending].filter((i) => (i.name === "user_message" || i.name === "agent_message") && i.text.trim());
      return el("div", { class: "bubbles" }, ...said.map((i) => {
        const user = i.name === "user_message";
        return el("div", { class: `b ${user ? "user" : "agent"}${i.row_id === null || i.row_id === undefined ? " pending" : ""}` },
          user ? document.createTextNode(i.text) : markdown(i.text),
          el("div", { class: "t", text: clock(i.at) }));
      }));
    },
  });
})();
