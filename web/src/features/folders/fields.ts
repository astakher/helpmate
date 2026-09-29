import type { FieldDef } from "../../api/types";

/** FormData -> {key: typed value}, skipping empty inputs. */
export function readFields(fields: FieldDef[], form: FormData): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = form.get(`field:${field.key}`);
    if (field.type === "bool") {
      values[field.key] = raw === "on";
      continue;
    }
    if (raw === null || raw === "") continue;
    values[field.key] = field.type === "number" || field.type === "rating" ? Number(raw) : String(raw);
  }
  return values;
}

export function formatValue(field: FieldDef, value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (field.type === "rating") return `${"★".repeat(Number(value))}${"☆".repeat(5 - Number(value))}`;
  if (field.type === "bool") return value ? "Yes" : "No";
  return String(value);
}
