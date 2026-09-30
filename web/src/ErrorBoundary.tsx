import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** When this changes (e.g. the route), a caught error is cleared and the page renders again. */
  resetKey?: unknown;
  /** Around the whole app: centred splash instead of an in-page panel. */
  fullPage?: boolean;
};
type State = { error: Error | null };

/**
 * Shows a message instead of a blank page when a component throws while rendering or in an
 * effect. Without it, one bad component unmounts the whole app (the Sep 29 `destroy is not a
 * function` bug looked like an empty page).
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("HelpMate UI error:", error, info.componentStack);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section
        className={`error-boundary ${this.props.fullPage ? "splash" : "page"}`}
        role="alert"
        aria-labelledby="error-boundary-heading"
      >
        <h1 id="error-boundary-heading">Something went wrong</h1>
        <p className="muted">
          This screen hit an error. Your data is safe: nothing changes without your approval.
        </p>
        <details>
          <summary>Technical details</summary>
          <pre className="error">{error.message}</pre>
        </details>
        <div className="error-boundary__actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </section>
    );
  }
}
