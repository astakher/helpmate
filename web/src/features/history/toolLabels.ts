/** What each of the assistant's tools does, in the owner's words. */

/** Actions the owner can pre-approve (Settings): "Let HelpMate … without asking". */
const ACTIONS: Record<string, string> = {
  create_reminder: "Set reminders",
  create_task: "Add tasks",
};

/** Read-only lookups as they read in the history: "HelpMate …". */
const LOOKUPS: Record<string, string> = {
  search_email: "searched your email",
  list_events: "checked your calendar",
  find_free_time: "looked for free time",
  list_tasks: "listed your tasks",
  list_reminders: "listed your reminders",
  list_memory: "listed what it remembers",
};

const plain = (tool: string) => tool.replaceAll("_", " ");

export const actionLabel = (tool: string) => ACTIONS[tool] ?? plain(tool);
export const lookupLabel = (tool: string) => LOOKUPS[tool] ?? `used ${plain(tool)}`;
