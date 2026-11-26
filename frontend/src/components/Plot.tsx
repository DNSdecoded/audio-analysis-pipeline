import { useEffect, useId, useRef, useState } from 'react';
import { AlertTriangle, BarChart3 } from 'lucide-react';
import { PLOT_CONFIG, baseLayout, themeFigure } from '../lib/plotTheme';
import { useWorkspace } from '../state/Workspace';

type PlotlyModule = typeof import('plotly.js-dist-min');
let plotlyPromise: Promise<PlotlyModule> | null = null;

/** Plotly is ~4.6 MB; load it on first chart render instead of at startup. */
export function loadPlotly(): Promise<PlotlyModule> {
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist-min').then((mod: any) => mod.default ?? mod);
  }
  return plotlyPromise;
}

interface PlotProps {
  data: any[];
  layout?: Record<string, any>;
  config?: Record<string, any>;
  height?: number | string;
  className?: string;
  onRelayout?: (event: any) => void;
  revision?: number;
  /** Accessible name for the chart (screen readers, tests). */
  title?: string;
  /** Short text alternative describing what the chart shows. */
  summary?: string;
  /** Message shown when there is no data to draw. */
  emptyMessage?: string;
}

function hasData(data: any[]): boolean {
  return data.some((trace) => {
    const series = trace?.z ?? trace?.y ?? trace?.x ?? trace?.r ?? trace?.values;
    return Array.isArray(series) && series.length > 0;
  });
}

export default function Plot({
  data,
  layout,
  config,
  height = 360,
  className,
  onRelayout,
  revision = 0,
  title,
  summary,
  emptyMessage = 'No data to display for this selection.',
}: PlotProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const callbackRef = useRef(onRelayout);
  const attachedRef = useRef(false);
  const summaryId = useId();
  const { theme, chartPrefs } = useWorkspace();
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  callbackRef.current = onRelayout;
  const empty = !hasData(data);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || empty) return;
    let cancelled = false;
    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !containerRef.current) return undefined;
        // Identity colours → active theme pair; axis/grid/surface from CSS tokens.
        const mergedLayout = baseLayout(themeFigure(layout ?? {}, theme));
        const themedData = themeFigure(data, theme);
        const mergedConfig = {
          ...PLOT_CONFIG,
          displayModeBar: chartPrefs.alwaysShowToolbar ? true : 'hover',
          ...(config ?? {}),
        };
        return Plotly.react(element, themedData, mergedLayout, mergedConfig).then(() => {
          if (cancelled) return;
          setStatus('ready');
          setError(null);
          if (!attachedRef.current) {
            (element as any).on?.('plotly_relayout', (event: any) => callbackRef.current?.(event));
            attachedRef.current = true;
          }
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatus('error');
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
    // theme is a dependency so axis/grid colours are re-read from CSS tokens.
  }, [data, layout, config, revision, theme, empty, chartPrefs.alwaysShowToolbar]);

  useEffect(() => {
    const element = containerRef.current;
    return () => {
      if (element && plotlyPromise) {
        void plotlyPromise.then((Plotly) => {
          try {
            Plotly.purge(element);
          } catch {
            /* already detached */
          }
        });
      }
      attachedRef.current = false;
    };
  }, []);

  if (empty) {
    return (
      <div className={`plot-state ${className ?? ''}`} style={{ minHeight: typeof height === 'number' ? Math.min(height, 220) : height }} role="note">
        <BarChart3 size={20} aria-hidden="true" />
        <span>{emptyMessage}</span>
      </div>
    );
  }

  return (
    <figure
      className={`plot-figure ${className ?? ''}`}
      aria-label={title ? `${title} (interactive chart)` : 'Interactive chart'}
      aria-describedby={summary ? summaryId : undefined}
    >
      <div
        ref={containerRef}
        className="plot-canvas"
        style={{ width: '100%', height }}
        aria-busy={status === 'loading'}
      />
      {status === 'loading' && (
        <div className="plot-overlay" aria-hidden="true">
          <span className="spinner" style={{ width: 18, height: 18 }} /> Loading chart…
        </div>
      )}
      {status === 'error' && (
        <div className="plot-overlay plot-overlay-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" /> Chart could not be drawn: {error}
        </div>
      )}
      {summary && (
        <figcaption id={summaryId} className="sr-only">
          {summary}
        </figcaption>
      )}
    </figure>
  );
}
