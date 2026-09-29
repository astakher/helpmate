// Friendly aliases for the generated contract types (src/api/schema.d.ts, from
// contracts/openapi.yaml). Never edit schema.d.ts by hand: run `npm run gen:api`.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ChatEvent = Schemas["ChatEvent"];
export type ChatMessage = Schemas["ChatMessage"];
export type ChatSession = Schemas["ChatSession"];
export type Proposal = Schemas["Proposal"];
export type ProposalStatus = Schemas["ProposalStatus"];
export type Reminder = Schemas["Reminder"];
export type Task = Schemas["Task"];
export type Horizon = Schemas["Horizon"];
export type Folder = Schemas["Folder"];
export type FieldDef = Schemas["FieldDef"];
export type FieldType = Schemas["FieldType"];
export type Item = Schemas["Item"];
export type MemoryFact = Schemas["MemoryFact"];
export type MemorySuggestion = Schemas["MemorySuggestion"];
export type NotificationSettings = Schemas["NotificationSettings"];
export type ToolInfo = Schemas["ToolInfo"];
export type User = Schemas["User"];
export type TodayOut = Schemas["TodayOut"];
export type HealthOut = Schemas["HealthOut"];
export type Decision = Schemas["DecisionIn"]["decision"];
export type Source = Schemas["PostMessageIn"]["source"];
