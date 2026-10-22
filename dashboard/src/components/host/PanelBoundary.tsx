/**
 * One error boundary per panel (16 §2s item 4b).
 *
 * The root route's errorComponent is the whole page: anything that throws
 * during render anywhere below it replaces the entire Command Center with
 * "This page didn't load — Try again / Go home". The 22 Oct soak showed that
 * really happening. A panel that throws must cost that panel and nothing else,
 * so every panel on every page is wrapped in one of these.
 *
 * When the panel is healthy this renders the child EXACTLY as the page would
 * have rendered it -- no extra element, no extra class -- so the healthy
 * dashboard's markup and layout are unchanged. The grid class is given to the
 * boundary, which passes it to the panel, so there is one place it is written
 * and the fallback can take the same slot in the grid.
 */
import { Component, Fragment, cloneElement, isValidElement, type ErrorInfo, type ReactElement, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export const PANEL_FAILED_TEXT = "This panel hit a problem.";
export const PANEL_RELOAD_TEXT = "Reload panel";

function PanelFallback({
  className,
  onReload,
}: {
  className?: string | undefined;
  onReload: () => void;
}) {
  return (
    <section className={cn("panel flex min-w-0 flex-col", className)} role="alert">
      <div className="flex min-h-28 flex-1 flex-col items-center justify-center gap-3 p-4 text-center">
        <TriangleAlert className="h-6 w-6 text-warning" />
        <p className="text-sm font-medium text-foreground">{PANEL_FAILED_TEXT}</p>
        <Button variant="outline" size="sm" onClick={onReload}>
          {PANEL_RELOAD_TEXT}
        </Button>
      </div>
    </section>
  );
}

interface Props {
  /** Named in the one console line, so the operator can say which panel it was. */
  name: string;
  className?: string | undefined;
  children: ReactNode;
}

interface State {
  failed: boolean;
  /** Bumped by "Reload panel"; it is the child's key, so the panel re-mounts. */
  attempt: number;
}

export class PanelBoundary extends Component<Props, State> {
  override state: State = { failed: false, attempt: 0 };

  static getDerivedStateFromError(): Pick<State, "failed"> {
    return { failed: true };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo) {
    // Once, to the console, and nowhere else: no editor telemetry, and nothing
    // from a panel's data -- the name, the error and React's own component
    // stack only (16 §2s item 4b).
    console.error(`[panel] ${this.props.name} hit a problem`, error, info.componentStack);
  }

  private reload = () => {
    this.setState((s) => ({ failed: false, attempt: s.attempt + 1 }));
  };

  override render() {
    const { children, className } = this.props;
    if (this.state.failed) {
      return <PanelFallback className={className} onReload={this.reload} />;
    }
    // The panel keeps every prop the page gave it and gains the grid class.
    // Only when there is one: cloning with an undefined className would wipe a
    // class the page had written on the panel itself.
    const child =
      className !== undefined && isValidElement(children)
        ? cloneElement(children as ReactElement<{ className?: string }>, { className })
        : children;
    // The key is what makes "Reload panel" a real re-mount rather than a
    // re-render of the component that just threw.
    return <Fragment key={this.state.attempt}>{child}</Fragment>;
  }
}
