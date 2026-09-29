import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { Decision, Proposal } from "./types";

export const keys = {
  health: ["health"] as const,
  proposals: (status?: string) => ["proposals", status ?? "all"] as const,
  today: ["today"] as const,
  reminders: ["reminders"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: async () => unwrap(await api.GET("/api/health")),
    refetchInterval: 15_000,
  });
}

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

export function useToday() {
  return useQuery({
    queryKey: keys.today,
    queryFn: async () => unwrap(await api.GET("/api/today")),
    refetchInterval: 30_000,
  });
}

export function useReminders() {
  return useQuery({
    queryKey: keys.reminders,
    queryFn: async () => unwrap(await api.GET("/api/reminders")),
    refetchInterval: 15_000,
  });
}

export async function fetchProposal(id: string): Promise<Proposal> {
  return unwrap(await api.GET("/api/proposals/{proposal_id}", { params: { path: { proposal_id: id } } }));
}

/** Anything a decision can change: refresh it all. */
export function useInvalidateAfterDecision() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      [["proposals"], keys.today, keys.reminders].map((queryKey) =>
        client.invalidateQueries({ queryKey }),
      ),
    );
}

export function useDecide() {
  const invalidate = useInvalidateAfterDecision();
  return useMutation({
    mutationFn: async ({ id, decision }: { id: string; decision: Decision }) =>
      unwrap(
        await api.POST("/api/proposals/{proposal_id}/decision", {
          params: { path: { proposal_id: id } },
          body: { decision },
        }),
      ),
    onSettled: invalidate,
  });
}

export function useCancelReminder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/reminders/{reminder_id}/cancel", {
          params: { path: { reminder_id: id } },
        }),
      ),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.reminders }),
        client.invalidateQueries({ queryKey: keys.today }),
      ]),
  });
}
