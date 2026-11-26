import { useId, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, CircleHelp, Info, MinusCircle, XCircle } from 'lucide-react';

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
  noPadding = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      <div className={noPadding ? 'card-body no-padding' : 'card-body'}>{children}</div>
    </section>
  );
}

export function Badge({
  children,
  variant = 'neutral',
  className = '',
}: {
  children: ReactNode;
  variant?: 'neutral' | 'accent' | 'success' | 'warning' | 'error' | 'info' | 'purple';
  className?: string;
}) {
  return <span className={`badge badge-${variant} ${className}`}>{children}</span>;
}

/** Display vocabulary for QC severities (backend: normal / information / warning / error). */
export const SEVERITY_DISPLAY: Record<string, { label: string; variant: 'success' | 'info' | 'warning' | 'error' | 'neutral' }> = {
  normal: { label: 'Pass', variant: 'success' },
  information: { label: 'Info', variant: 'info' },
  info: { label: 'Info', variant: 'info' },
  warning: { label: 'Warning', variant: 'warning' },
  error: { label: 'Critical', variant: 'error' },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const display = SEVERITY_DISPLAY[severity] ?? { label: severity ? severity.charAt(0).toUpperCase() + severity.slice(1) : 'Unknown', variant: 'neutral' as const };
  const Icon = severity === 'error' ? XCircle : severity === 'warning' ? AlertTriangle : severity === 'normal' ? CheckCircle2 : Info;
  // Icon + text: status is never conveyed by colour alone.
  return (
    <Badge variant={display.variant}>
      <Icon size={12} aria-hidden="true" /> {display.label}
    </Badge>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  tone?: 'default' | 'accent' | 'success' | 'warning' | 'error';
}) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div
      className="progress-wrap"
      role="progressbar"
      aria-label={label ?? 'Progress'}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(Math.max(0, Math.min(100, value)))}
    >
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
      <span className="progress-label">{Math.round(value)}%</span>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function InfoNote({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'error' | 'success' }) {
  const Icon = tone === 'warning' || tone === 'error' ? AlertTriangle : tone === 'success' ? CheckCircle2 : Info;
  return (
    <div className={`info-note info-note-${tone}`}>
      <Icon size={16} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function Spinner({ size = 18, label = 'Loading' }: { size?: number; label?: string }) {
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label={label} />;
}

/**
 * Accessible explanation popover: opens on hover, keyboard focus or tap and is
 * announced through aria-describedby (WCAG 1.4.13: dismissible with Escape,
 * hoverable, persistent while focused).
 */
export function InfoTip({ text, label = 'More information' }: { text: ReactNode; label?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className={`infotip ${open ? 'open' : ''}`} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="infotip-trigger"
        aria-label={label}
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onMouseEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
        }}
      >
        <CircleHelp size={13} aria-hidden="true" />
      </button>
      <span role="tooltip" id={id} className="infotip-bubble">
        {text}
      </span>
    </span>
  );
}

export type MetricStatus = 'pass' | 'info' | 'warning' | 'critical' | 'unavailable' | 'none';

const METRIC_STATUS: Record<MetricStatus, { label: string; Icon: typeof Info }> = {
  pass: { label: 'Pass', Icon: CheckCircle2 },
  info: { label: 'Info', Icon: Info },
  warning: { label: 'Warning', Icon: AlertTriangle },
  critical: { label: 'Critical', Icon: XCircle },
  unavailable: { label: 'Not available', Icon: MinusCircle },
  none: { label: '', Icon: Info },
};

export function statusFromSeverity(severity: string | null | undefined): MetricStatus {
  switch (severity) {
    case 'normal':
      return 'pass';
    case 'information':
      return 'info';
    case 'warning':
      return 'warning';
    case 'error':
      return 'critical';
    default:
      return 'none';
  }
}

/**
 * One technical measurement: name, value, unit, status, explanation and
 * whether it is a direct measurement or an algorithmic estimate.  A missing
 * value is shown as "Not available" — never with a success status.
 */
export function MetricCard({
  label,
  value,
  unit,
  status = 'none',
  explanation,
  kind = 'measured',
  confidence,
  hint,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  status?: MetricStatus;
  explanation?: ReactNode;
  kind?: 'measured' | 'estimate';
  confidence?: string | null;
  hint?: ReactNode;
}) {
  const missing = value === null || value === undefined || value === '—' || value === '';
  const effective: MetricStatus = missing ? 'unavailable' : status;
  const { label: statusLabel, Icon } = METRIC_STATUS[effective];
  return (
    <div className={`metric metric-${effective}`}>
      <div className="metric-head">
        <span className="metric-label">{label}</span>
        {explanation && <InfoTip text={explanation} label={`About ${label}`} />}
      </div>
      <div className="metric-value">
        {missing ? <span className="metric-missing">—</span> : value}
        {!missing && unit && <span className="metric-unit">{unit}</span>}
      </div>
      <div className="metric-foot">
        {effective !== 'none' && (
          <span className={`metric-status metric-status-${effective}`}>
            <Icon size={12} aria-hidden="true" /> {statusLabel}
          </span>
        )}
        <span className={`metric-kind metric-kind-${kind}`}>
          {kind === 'estimate' ? `Estimate${confidence && !missing && confidence !== 'unavailable' ? ` · ${confidence} confidence` : ''}` : 'Measured'}
        </span>
      </div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  );
}

/** Horizontally scrollable table region that keyboard users can reach and scroll. */
export function TableWrap({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={`table-wrap ${className}`} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export function ToggleGroup<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? 'active' : ''}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ConfidenceBar({ value, label }: { value: number | null | undefined; label?: string }) {
  const percent = Math.round(Math.max(0, Math.min(1, Number(value ?? 0))) * 100);
  const tone = percent >= 65 ? 'success' : percent >= 40 ? 'warning' : 'error';
  return (
    <div className="confidence">
      <div className="confidence-top">
        <span>{label ?? 'Confidence'}</span>
        <span>{percent}%</span>
      </div>
      <div className="confidence-track">
        <div className={`confidence-fill tone-${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function KeyValue({ rows }: { rows: { label: string; value: ReactNode; mono?: boolean }[] }) {
  return (
    <dl className="key-value">
      {rows.map((row) => (
        <div key={row.label} className="kv-row">
          <dt>{row.label}</dt>
          <dd className={row.mono ? 'mono' : ''}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="section-actions">{actions}</div>}
    </div>
  );
}
