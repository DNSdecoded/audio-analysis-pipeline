import { Check } from 'lucide-react';
import type { FileRecord } from '../types';
import { statusClass } from '../lib/format';

export function FileSelect({
  files,
  selected,
  onChange,
  multiple = false,
  label,
  emptyText = 'No audio files uploaded yet.',
  max,
}: {
  files: FileRecord[];
  selected: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
  label?: string;
  emptyText?: string;
  max?: number;
}) {
  const toggle = (id: string) => {
    if (!multiple) {
      onChange([id]);
      return;
    }
    if (selected.includes(id)) {
      if (selected.length === 1) return;
      onChange(selected.filter((value) => value !== id));
    } else {
      if (max && selected.length >= max) {
        onChange([...selected.slice(1), id]);
      } else {
        onChange([...selected, id]);
      }
    }
  };

  return (
    <div className="file-select-block">
      {label && <div className="field-label">{label}</div>}
      {files.length === 0 ? (
        <p className="muted small">{emptyText}</p>
      ) : (
        <div className="file-select">
          {files.map((file) => {
            const active = selected.includes(file.id);
            return (
              <button
                key={file.id}
                type="button"
                className={`file-chip ${active ? 'active' : ''}`}
                onClick={() => toggle(file.id)}
                aria-pressed={active}
                title={`${file.original_name} — ${file.metadata?.format ?? 'audio'}`}
              >
                <span className={`status-dot ${statusClass(file.status)}`} />
                <span className="file-chip-text">
                  <span className="file-chip-name">{file.original_name}</span>
                  <span className="file-chip-meta">
                    {file.metadata?.format ?? '—'} · {file.metadata?.duration ? `${Number(file.metadata.duration).toFixed(1)} s` : '—'}
                    {file.has_analysis ? ' · analysed' : ''}
                  </span>
                </span>
                {active && <Check className="file-chip-check" size={14} aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
