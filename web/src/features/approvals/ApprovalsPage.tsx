import { usePendingProposals, useRecentProposals } from "../../api/queries";
import { ProposalCard } from "./ProposalCard";

export function ApprovalsPage() {
  const pending = usePendingProposals();
  const recent = useRecentProposals();
  const decided = (recent.data ?? []).filter((p) => p.status !== "pending").slice(0, 10);

  return (
    <section className="page" aria-labelledby="approvals-heading">
      <h1 id="approvals-heading">Approvals</h1>
      <p className="muted">HelpMate never changes your data or sends anything until you approve it.</p>

      <h2>Waiting for you</h2>
      {pending.isLoading && <p>Loading…</p>}
      {pending.data?.length === 0 && <p className="muted">Nothing to approve.</p>}
      <div className="stack">
        {pending.data?.map((p) => <ProposalCard key={p.id} proposal={p} />)}
      </div>

      {decided.length > 0 && (
        <>
          <h2>Recently decided</h2>
          <div className="stack">
            {decided.map((p) => (
              <ProposalCard key={p.id} proposal={p} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
