import type { Horizon } from "../../api/types";

export const HORIZONS: { value: Horizon; label: string }[] = [
  { value: "week", label: "This week" },
  { value: "term", label: "This term" },
  { value: "year", label: "This year" },
  { value: "someday", label: "Someday" },
];
