type JsonSchema = {
  type?: string;
  format?: string;
  enum?: string[];
  title?: string;
  items?: JsonSchema;
  $ref?: string;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  $defs?: Record<string, JsonSchema>;
};

export type SchemaField = {
  name: string;
  label: string;
  kind: "text" | "multiline" | "list" | "datetime" | "enum" | "number" | "bool";
  options?: string[];
  required: boolean;
};

/**
 * Turns a tool's JSON Schema (GET /api/tools) into form fields, so any tool Workstream A adds
 * gets an Edit form without UI changes. Handles what pydantic emits: $ref enums, Optional (anyOf
 * with null), date-time strings, numbers and booleans, plus lists of strings (edited as a
 * comma-separated line, e.g. email recipients) and `format: "multiline"` (a textarea, e.g. an
 * email body).
 */
export function schemaFields(parameters: Record<string, unknown>): SchemaField[] {
  const schema = parameters as JsonSchema;
  const resolve = (s: JsonSchema): JsonSchema => {
    if (s.$ref) return resolve(schema.$defs?.[s.$ref.split("/").pop()!] ?? {});
    const nonNull = s.anyOf?.filter((x) => x.type !== "null");
    if (nonNull?.length === 1) return { ...resolve(nonNull[0]), title: s.title ?? nonNull[0].title };
    return s;
  };
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const s = resolve(raw);
    const label = raw.title ?? s.title ?? name;
    const required = schema.required?.includes(name) ?? false;
    if (s.enum) return { name, label, kind: "enum", options: s.enum, required };
    if (s.format === "date-time") return { name, label, kind: "datetime", required };
    if (s.format === "multiline") return { name, label, kind: "multiline", required };
    if (s.type === "array" && s.items?.type === "string") return { name, label, kind: "list", required };
    if (s.type === "integer" || s.type === "number") return { name, label, kind: "number", required };
    if (s.type === "boolean") return { name, label, kind: "bool", required };
    return { name, label, kind: "text", required };
  });
}

/** ISO timestamp -> value for <input type="datetime-local">, in the viewer's local time. */
export function toLocalInput(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
