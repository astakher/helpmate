import { NavLink, Route, Routes } from "react-router";
import { useHealth, usePendingProposals } from "./api/queries";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { ChatPage } from "./features/chat/ChatPage";
import { StatusPage } from "./features/status/StatusPage";
import { TodayPage } from "./features/today/TodayPage";

export function App() {
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <span className="brand" aria-hidden="true">
          HelpMate
        </span>
        <Nav />
        <FakeChip />
      </header>
      <main id="main" className="main">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/today" element={<TodayPage />} />
          <Route path="/reminders" element={<TodayPage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="*" element={<ChatPage />} />
        </Routes>
      </main>
    </div>
  );
}

function Nav() {
  const pending = usePendingProposals().data?.length ?? 0;
  return (
    <nav aria-label="Main" className="nav">
      <NavLink to="/" end>
        Chat
      </NavLink>
      <NavLink to="/approvals">
        Approvals
        {pending > 0 && (
          <span className="count">
            {pending}
            <span className="visually-hidden"> pending</span>
          </span>
        )}
      </NavLink>
      <NavLink to="/today">Today</NavLink>
      <NavLink to="/status">Status</NavLink>
    </nav>
  );
}

/** Always visible while any part of the system is a fake, so a demo never misleads. */
function FakeChip() {
  const adapters = Object.values(useHealth().data?.adapters ?? {});
  const fakes = adapters.filter((a) => a.fake).length;
  if (!adapters.length || fakes === 0) return null;
  return (
    <NavLink to="/status" className="chip chip--fake" title="Some parts are simulated">
      {fakes} of {adapters.length} simulated
    </NavLink>
  );
}
