import type { FieldDef } from "../../api/types";

/** One input for a custom-folder field, chosen by its type. Values are read with FormData. */
export function FieldInput({ field }: { field: FieldDef }) {
  const name = `field:${field.key}`;
  switch (field.type) {
    case "number":
      return (
        <label>
          {field.label}
          <input type="number" name={name} step="any" />
        </label>
      );
    case "date":
      return (
        <label>
          {field.label}
          <input type="date" name={name} />
        </label>
      );
    case "select":
      return (
        <label>
          {field.label}
          <select name={name} defaultValue="">
            <option value="">—</option>
            {(field.options ?? []).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      );
    case "rating":
      return (
        <fieldset className="rating">
          <legend>{field.label}</legend>
          {[1, 2, 3, 4, 5].map((n) => (
            <label key={n} className="inline">
              <input type="radio" name={name} value={n} aria-label={`${n} out of 5`} />
              {n}
            </label>
          ))}
        </fieldset>
      );
    case "bool":
      return (
        <label className="inline">
          <input type="checkbox" name={name} /> {field.label}
        </label>
      );
    default:
      return (
        <label>
          {field.label}
          <input name={name} />
        </label>
      );
  }
}
