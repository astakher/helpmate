import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Same-origin always: in dev Vite proxies /api to FastAPI, in prod FastAPI serves this app.
export const origin = globalThis.location?.origin ?? "";

export const api = createClient<paths>({
  baseUrl: origin,
  credentials: "same-origin",
  // Look fetch up on every call: openapi-fetch otherwise captures it at import time, before
  // test mocks (MSW) or any other wrapper get a chance to install themselves.
  fetch: (request) => globalThis.fetch(request),
});

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Returns the body of a successful response, or throws an ApiError with the server's detail. */
export function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, describe(result.error));
  }
  return result.data as T;
}

function describe(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return "request failed";
}
