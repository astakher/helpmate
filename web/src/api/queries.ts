import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api, ApiError, unwrap } from "./client";
import type {
  Decision,
  FieldDef,
  Horizon,
  NotificationSettings,
  Proposal,
  SubscriptionIn,
  Task,
} from "./types";

export const keys = {
  health: ["health"] as const,
  me: ["me"] as const,
  tools: ["tools"] as const,
  proposals: (status?: string) => ["proposals", status ?? "all"] as const,
  today: ["today"] as const,
  reminders: ["reminders"] as const,
  tasks: (horizon?: Horizon) => ["tasks", horizon ?? "all"] as const,
  folders: ["folders"] as const,
  items: (folderId: string) => ["items", folderId] as const,
  suggestions: ["memory", "suggestions"] as const,
  facts: ["memory", "facts"] as const,
  notificationSettings: ["settings", "notifications"] as const,
  chats: ["chat", "sessions"] as const,
  week: ["week"] as const,
  inbox: ["inbox"] as const,
  email: (messageId: string) => ["email", messageId] as const,
  documents: ["documents"] as const,
};

function useInvalidate() {
  const client = useQueryClient();
  return (...queryKeys: QueryKey[]) =>
    Promise.all(queryKeys.map((queryKey) => client.invalidateQueries({ queryKey })));
}

// --- system ---

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: async () => unwrap(await api.GET("/api/health")),
    refetchInterval: 15_000,
  });
}

export function useTools() {
  return useQuery({
    queryKey: keys.tools,
    queryFn: async () => unwrap(await api.GET("/api/tools")),
    staleTime: Infinity,
  });
}

// --- auth ---

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => unwrap(await api.GET("/api/me")),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: async (body: { username: string; password: string }) =>
      unwrap(await api.POST("/api/auth/login", { body })),
  });
}

export function useVerifyMfa() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: { challenge_id: string; code: string }) =>
      unwrap(await api.POST("/api/auth/mfa", { body })),
    onSuccess: () => invalidate(keys.me),
  });
}

export function useEnrollMfa() {
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/mfa/enroll")),
  });
}

/** Finish enrolment with the first code from the authenticator app. Only then is 2FA on. */
export function useConfirmMfa() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (code: string) =>
      unwrap(await api.POST("/api/auth/mfa/enroll/confirm", { body: { code } })),
    onSuccess: () => invalidate(keys.me),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/logout")),
    onSuccess: () => client.resetQueries(),
  });
}

// --- proposals ---

export function usePendingProposals() {
  return useQuery({
    queryKey: keys.proposals("pending"),
    queryFn: async () =>
      unwrap(await api.GET("/api/proposals", { params: { query: { status: "pending" } } })),
  });
}

export function useRecentProposals() {
  return useQuery({
    queryKey: keys.proposals(),
    queryFn: async () => unwrap(await api.GET("/api/proposals")),
  });
}

export async function fetchProposal(id: string): Promise<Proposal> {
  return unwrap(
    await api.GET("/api/proposals/{proposal_id}", { params: { path: { proposal_id: id } } }),
  );
}

export function useDecide() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({
      id,
      decision,
      args,
    }: {
      id: string;
      decision: Decision;
      args?: Record<string, unknown>;
    }) =>
      unwrap(
        await api.POST("/api/proposals/{proposal_id}/decision", {
          params: { path: { proposal_id: id } },
          body: { decision, args: args ?? null },
        }),
      ),
    // a decision can create reminders or tasks: refresh everything that shows them
    onSettled: () => invalidate(["proposals"], keys.today, keys.reminders, ["tasks"]),
  });
}

// --- today & reminders ---

export function useToday() {
  return useQuery({
    queryKey: keys.today,
    queryFn: async () => unwrap(await api.GET("/api/today")),
    refetchInterval: 60_000, // each refresh also reads Google Calendar + Gmail (plus on focus)
  });
}

/** The next 7 days: events, free time, reminders, tasks due, and week tasks with no date. */
export function useWeek() {
  return useQuery({
    queryKey: keys.week,
    queryFn: async () => unwrap(await api.GET("/api/week")),
  });
}

/** Unread mail sorted by the local model (needs a reply / FYI / low). Slow-ish the first time
 * (~1 s per email), cached on the server after that, so no polling here. */
export function useInbox() {
  return useQuery({
    queryKey: keys.inbox,
    queryFn: async () => unwrap(await api.GET("/api/inbox")),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

/** One email in full (plain text), fetched only when the owner opens it; an email doesn't change. */
export function useEmail(messageId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.email(messageId),
    queryFn: async () => unwrap(await api.GET("/api/inbox/{message_id}", { params: { path: { message_id: messageId } } })),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

/** A reply drafted by the local model, as a send_email approval card (to the sender only). */
export function useDraftReply() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (messageId: string) =>
      unwrap(await api.POST("/api/inbox/{message_id}/draft-reply", { params: { path: { message_id: messageId } } })),
    onSuccess: () => invalidate(["proposals"]),
  });
}

// --- documents (the file vault) ---

export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: async () => unwrap(await api.GET("/api/documents")),
  });
}

/** Upload a file as the raw request body (like voice recordings); the server reads and indexes it. */
export function useUploadDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (file: File) =>
      unwrap(
        await api.POST("/api/documents", {
          params: { query: { name: file.name } },
          body: file as unknown as string,
          bodySerializer: (body) => body as unknown as BodyInit,
          headers: { "Content-Type": file.type || "application/octet-stream" },
        }),
      ),
    onSettled: () => invalidate(keys.documents),
  });
}

export function useDeleteDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (documentId: string) =>
      unwrap(await api.DELETE("/api/documents/{document_id}", { params: { path: { document_id: documentId } } })),
    onSettled: () => invalidate(keys.documents),
  });
}

/** An answer from the owner's documents only, citing passages as [n]. */
export function useAskDocuments() {
  return useMutation({
    mutationFn: async (question: string) => unwrap(await api.POST("/api/documents/ask", { body: { question } })),
  });
}

/** "Find time": proposes a calendar event for the task in the first free slot (an approval card). */
export function useScheduleTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ taskId, minutes = 60 }: { taskId: string; minutes?: number }) =>
      unwrap(await api.POST("/api/week/schedule-task", { body: { task_id: taskId, minutes } })),
    onSuccess: () => invalidate(["proposals"]), // every status: the nav's pending count too
  });
}

export function useReminders() {
  return useQuery({
    queryKey: keys.reminders,
    queryFn: async () => unwrap(await api.GET("/api/reminders")),
    refetchInterval: 15_000,
  });
}

export function useCancelReminder() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/reminders/{reminder_id}/cancel", {
          params: { path: { reminder_id: id } },
        }),
      ),
    onSettled: () => invalidate(keys.reminders, keys.today),
  });
}

// --- tasks ---

export function useTasks(horizon: Horizon) {
  return useQuery({
    queryKey: keys.tasks(horizon),
    queryFn: async () => unwrap(await api.GET("/api/tasks", { params: { query: { horizon } } })),
  });
}

export function useCreateTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: { title: string; horizon: Horizon }) =>
      unwrap(await api.POST("/api/tasks", { body })),
    onSettled: () => invalidate(["tasks"], keys.today),
  });
}

export function useUpdateTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({
      id,
      ...changes
    }: { id: string } & Partial<Pick<Task, "title" | "done" | "horizon">>) =>
      unwrap(
        await api.PATCH("/api/tasks/{task_id}", {
          params: { path: { task_id: id } },
          body: changes,
        }),
      ),
    onSettled: () => invalidate(["tasks"], keys.today),
  });
}

// --- folders & items ---

export function useFolders() {
  return useQuery({
    queryKey: keys.folders,
    queryFn: async () => unwrap(await api.GET("/api/folders")),
  });
}

export function useCreateFolder() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: { name: string; fields: FieldDef[] }) =>
      unwrap(await api.POST("/api/folders", { body })),
    onSettled: () => invalidate(keys.folders),
  });
}

export function useItems(folderId: string) {
  return useQuery({
    queryKey: keys.items(folderId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/folders/{folder_id}/items", {
          params: { path: { folder_id: folderId } },
        }),
      ),
  });
}

export function useCreateItem(folderId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: { title: string; fields: Record<string, unknown> }) =>
      unwrap(
        await api.POST("/api/folders/{folder_id}/items", {
          params: { path: { folder_id: folderId } },
          body,
        }),
      ),
    onSettled: () => invalidate(keys.items(folderId)),
  });
}

// --- memory ---

export function useSuggestions() {
  return useQuery({
    queryKey: keys.suggestions,
    queryFn: async () => unwrap(await api.GET("/api/memory/suggestions")),
  });
}

export function useDecideSuggestion() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, decision }: { id: string; decision: "approve" | "reject" }) =>
      unwrap(
        await api.POST("/api/memory/suggestions/{suggestion_id}/decision", {
          params: { path: { suggestion_id: id } },
          body: { decision },
        }),
      ),
    onSettled: () => invalidate(keys.suggestions, keys.facts),
  });
}

export function useFacts() {
  return useQuery({
    queryKey: keys.facts,
    queryFn: async () => unwrap(await api.GET("/api/memory/facts")),
  });
}

// --- chats (the sidebar on the Chat page) ---

/** Every chat that has a message, most recent activity first, titled by its first message. */
export function useChatSessions() {
  return useQuery({
    queryKey: keys.chats,
    queryFn: async () => unwrap(await api.GET("/api/chat/sessions")),
  });
}

/** Deletes the chat and its messages for good (its approval cards stay on Approvals). */
export async function deleteChatSession(sessionId: string): Promise<void> {
  try {
    unwrap(await api.DELETE("/api/chat/sessions/{session_id}", { params: { path: { session_id: sessionId } } }));
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error; // already gone is fine
  }
}

export function useUpdateFact() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, text }: { id: string; text: string }) =>
      unwrap(
        await api.PATCH("/api/memory/facts/{fact_id}", {
          params: { path: { fact_id: id } },
          body: { text },
        }),
      ),
    onSettled: () => invalidate(keys.facts),
  });
}

export function useDeleteFact() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/memory/facts/{fact_id}", { params: { path: { fact_id: id } } })),
    onSettled: () => invalidate(keys.facts),
  });
}

export async function fetchExport() {
  return unwrap(await api.GET("/api/export"));
}

// --- settings ---

export function useNotificationSettings() {
  return useQuery({
    queryKey: keys.notificationSettings,
    queryFn: async () => unwrap(await api.GET("/api/settings/notifications")),
  });
}

export function useSaveNotificationSettings() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: NotificationSettings) =>
      unwrap(await api.PUT("/api/settings/notifications", { body })),
    onSettled: () => invalidate(keys.notificationSettings),
  });
}

// --- Web Push (Part C) ---

export function useVapidKey() {
  return useQuery({
    queryKey: ["push", "vapid-public-key"],
    queryFn: async () => unwrap(await api.GET("/api/push/vapid-public-key")).public_key ?? null,
    staleTime: Infinity,
  });
}

export async function saveSubscription(body: SubscriptionIn) {
  unwrap(await api.POST("/api/push/subscriptions", { body }));
}

export async function removeSubscription(endpoint: string) {
  unwrap(await api.DELETE("/api/push/subscriptions", { body: { endpoint } }));
}

export async function sendTestPush() {
  return unwrap(await api.POST("/api/push/test"));
}

export async function fetchDeliveries() {
  return unwrap(await api.GET("/api/push/deliveries"));
}

// --- Voice (Part C) ---

/** Upload a recording as a raw body (never multipart, so the server never spools it to disk). */
export async function transcribeAudio(audio: Blob, language?: string) {
  return unwrap(
    await api.POST("/api/voice/transcribe", {
      params: { query: language ? { language } : {} },
      body: audio as unknown as string,
      bodySerializer: (body) => body as unknown as BodyInit,
      headers: { "Content-Type": audio.type || "audio/webm" },
    }),
  );
}

/** Kokoro TTS on the server -> a WAV blob. */
export async function synthesizeSpeech(text: string, voice?: string): Promise<Blob> {
  const result = await api.POST("/api/voice/speak", { body: { text, voice }, parseAs: "blob" });
  return unwrap(result) as Blob;
}
