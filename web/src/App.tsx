import { NavLink, Route, Routes, useLocation } from "react-router";
import { useHealth, usePendingProposals } from "./api/queries";
import { ErrorBoundary } from "./ErrorBoundary";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuthGate } from "./features/auth/AuthGate";
import { ChatPage } from "./features/chat/ChatPage";
import { ChatProvider } from "./features/chat/ChatProvider";
import { FolderPage } from "./features/folders/FolderPage";
import { FoldersPage } from "./features/folders/FoldersPage";
import { MemoryPage } from "./features/memory/MemoryPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { StatusPage } from "./features/status/StatusPage";
import { TasksPage } from "./features/tasks/TasksPage";
import { TodayPage } from "./features/today/TodayPage";
import { WeekPage } from "./features/week/WeekPage";
import { InboxPage } from "./features/inbox/InboxPage";
import { DocumentsPage } from "./features/documents/DocumentsPage";

export function App() {
  const { pathname } = useLocation();
  return (
    <AuthGate>
      {/* above the routes: the conversation survives going to another page and back */}
      <ChatProvider>
        <div className="shell">
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          <header className="topbar">
            <span className="brand" aria-hidden="true">
              HelpMate
            </span>
            <FakeChip />
            <Nav />
          </header>
          <main id="main" className="main">
            {/* a page error keeps the nav usable; going to another page clears it */}
            <ErrorBoundary resetKey={pathname}>
              <Routes>
                <Route path="/" element={<ChatPage />} />
                <Route path="/approvals" element={<ApprovalsPage />} />
                <Route path="/today" element={<TodayPage />} />
                <Route path="/week" element={<WeekPage />} />
                <Route path="/inbox" element={<InboxPage />} />
                <Route path="/documents" element={<DocumentsPage />} />
                <Route path="/reminders" element={<TodayPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/folders" element={<FoldersPage />} />
                <Route path="/folders/:folderId" element={<FolderPage />} />
                <Route path="/memory" element={<MemoryPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/status" element={<StatusPage />} />
                <Route path="*" element={<ChatPage />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </ChatProvider>
    </AuthGate>
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
      <NavLink to="/week">Week</NavLink>
      <NavLink to="/inbox">Inbox</NavLink>
      <NavLink to="/documents">Documents</NavLink>
      <NavLink to="/tasks">Tasks</NavLink>
      <NavLink to="/folders">Folders</NavLink>
      <NavLink to="/memory">Memory</NavLink>
      <NavLink to="/settings">Settings</NavLink>
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
