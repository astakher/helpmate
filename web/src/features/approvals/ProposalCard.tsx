import { useState } from "react";
import { ApiError } from "../../api/client";
import { fetchProposal, useDecide } from "../../api/queries";
import type { Decision, Proposal } from "../../api/types";

const OUTCOME: Record<Proposal["status"], string> = {
  pending: "Waiting for you",
  approved: "Approved",
  executed: "Done",
  rejected: "Cancelled",
  failed: "Failed",
};

/**
 * An approval card: the only way an agent-initiated write ever runs.
 * The same card appears inline in chat and on the Approvals page. If it was decided elsewhere,
 * the server answers 409 and the card refreshes itself.
 */
export function ProposalCard({ proposal }: { proposal: Proposal }) {
  // The latest server answer for this card wins over the (possibly stale) prop.
  const [decided, setDecided] = useState<Proposal | null>(null);
  const current = decided?.id === proposal.id ? decided : proposal;
  const decide = useDecide();
  const titleId = `proposal-${current.id}-title`;

  async function onDecision(decision: Decision) {
    try {
      setDecided(await decide.mutateAsync({ id: current.id, decision }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setDecided(await fetchProposal(current.id));
      }
    }
  }

  const pending = current.status === "pending";
  const external = current.risk === "external";

  return (
    <article className={`card proposal proposal--${current.status}`} aria-labelledby={titleId}>
      <p className={`badge ${external ? "badge--warn" : ""}`}>
        {external ? "Leaves this device — needs approval" : "Needs your approval"}
      </p>
      <h3 id={titleId} className="proposal__title">
        {current.title}
      </h3>
      {current.summary && <p className="proposal__summary">{current.summary}</p>}
      {current.preview && (
        <pre className="proposal__preview" tabIndex={0} aria-label="Full preview">
          {current.preview}
        </pre>
      )}

      {pending ? (
        <div className="proposal__actions">
          <button
            type="button"
            className="btn btn--primary"
            disabled={decide.isPending}
            onClick={() => onDecision("approve")}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn"
            disabled={decide.isPending}
            onClick={() => onDecision("reject")}
          >
            Cancel
          </button>
        </div>
      ) : (
        <p className="proposal__outcome" role="status">
          {OUTCOME[current.status]}
          {current.result ? ` — ${current.result}` : ""}
        </p>
      )}
      {decide.isError && !(decide.error instanceof ApiError && decide.error.status === 409) && (
        <p className="error" role="alert">
          Couldn't save that decision: {decide.error.message}
        </p>
      )}
    </article>
  );
}
