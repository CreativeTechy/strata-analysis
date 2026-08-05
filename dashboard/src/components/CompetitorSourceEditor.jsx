/**
 * Shared UI for the manual-first competitor flow: creating a competitor with
 * sources in one shot, and adding one more source to an existing competitor.
 * Used by both CompetitorOnboarding (step 3) and CompetitorWorkspace (the
 * competitors panel), so the two surfaces stay in sync rather than drifting.
 */

import { useState } from 'react';
import { AlertTriangle, Loader2, Plus, Trash2 } from 'lucide-react';
import {
  SOURCE_KIND_OPTIONS, TERM_SOURCE_TYPES, TERM_SOURCE_PLACEHOLDERS, isPlausibleUrl,
} from '../competitorApi.js';

function emptySource() {
  return { platform: 'web', url: '', handle: '' };
}

/** One source row's inputs. Term-type platforms (hashtag/keyword/username) take a
 *  bare name instead of a URL — the real URL is derived server-side — so they get a
 *  single input bound to `handle` instead of the usual URL + optional-handle pair. */
function SourceRowFields({ row, onChange }) {
  if (TERM_SOURCE_TYPES.has(row.platform)) {
    return (
      <input
        className="cs-input"
        style={{ flex: '1 1 220px' }}
        placeholder={TERM_SOURCE_PLACEHOLDERS[row.platform] || 'Value'}
        value={row.handle}
        onChange={(event) => onChange({ handle: event.target.value })}
      />
    );
  }
  return (
    <>
      <input
        className="cs-input"
        style={{ flex: '1 1 220px' }}
        placeholder="https://..."
        value={row.url}
        onChange={(event) => onChange({ url: event.target.value })}
      />
      <input
        className="cs-input"
        style={{ flex: '0 1 140px' }}
        placeholder="display name (optional)"
        value={row.handle}
        onChange={(event) => onChange({ handle: event.target.value })}
      />
    </>
  );
}

/** Name/website/description + a dynamic list of source rows, for creating a
 *  competitor and its sources on one screen. Sources are optional — a
 *  competitor can be added with none and get sources added later. */
export function AddCompetitorForm({ onSubmit, busy, submitLabel = 'Add competitor' }) {
  const [name, setName] = useState('');
  const [website, setWebsite] = useState('');
  const [description, setDescription] = useState('');
  const [sources, setSources] = useState([emptySource()]);
  const [errors, setErrors] = useState({});

  const updateSource = (index, patch) => {
    setSources((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeSource = (index) => {
    setSources((current) => current.filter((_, i) => i !== index));
  };

  const addSourceRow = () => setSources((current) => [...current, emptySource()]);

  const submit = async () => {
    const nextErrors = {};
    if (!name.trim()) nextErrors.name = 'A competitor name is required.';

    const usable = sources.filter((row) => row.url.trim() || row.handle.trim());
    usable.forEach((row, index) => {
      if (TERM_SOURCE_TYPES.has(row.platform)) {
        if (!row.handle.trim()) nextErrors[`source-${index}`] = 'Enter a value.';
      } else if (!isPlausibleUrl(row.url)) {
        nextErrors[`source-${index}`] = 'Enter a valid URL.';
      }
    });

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    await onSubmit({
      name: name.trim(),
      website: website.trim() || null,
      description: description.trim() || null,
      sources: usable.map((row) => (
        TERM_SOURCE_TYPES.has(row.platform)
          ? { platform: row.platform, url: '', handle: row.handle.trim() }
          : { platform: row.platform, url: row.url.trim(), handle: row.handle.trim() || null }
      )),
    });

    setName('');
    setWebsite('');
    setDescription('');
    setSources([emptySource()]);
    setErrors({});
  };

  return (
    <div>
      <div className="cs-grid-2">
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-manual-name">Competitor name</label>
          <input
            id="cs-manual-name"
            className="cs-input"
            value={name}
            placeholder="Acme Inc."
            onChange={(event) => setName(event.target.value)}
          />
          {errors.name ? <div className="cs-source-error">{errors.name}</div> : null}
        </div>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-manual-website">
            Website<span className="cs-label-hint">optional</span>
          </label>
          <input
            id="cs-manual-website"
            className="cs-input"
            value={website}
            placeholder="acme.com"
            onChange={(event) => setWebsite(event.target.value)}
          />
        </div>
      </div>

      <div className="cs-field">
        <label className="cs-label" htmlFor="cs-manual-desc">
          Description<span className="cs-label-hint">optional</span>
        </label>
        <input
          id="cs-manual-desc"
          className="cs-input"
          value={description}
          placeholder="What they do, briefly"
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>

      <label className="cs-label">Sources<span className="cs-label-hint">optional — add now or later</span></label>
      {sources.map((row, index) => (
        <div key={index} className="cs-source-row">
          <select
            className="cs-select"
            value={row.platform}
            onChange={(event) => updateSource(index, { platform: event.target.value })}
          >
            {SOURCE_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <SourceRowFields row={row} onChange={(patch) => updateSource(index, patch)} />
          {sources.length > 1 ? (
            <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removeSource(index)} aria-label="Remove source">
              <Trash2 size={13} />
            </button>
          ) : null}
          {errors[`source-${index}`] ? (
            <div className="cs-source-error" style={{ width: '100%' }}>
              <AlertTriangle size={12} style={{ marginRight: 4, verticalAlign: -1 }} />
              {errors[`source-${index}`]}
            </div>
          ) : null}
        </div>
      ))}
      <button type="button" className="cs-btn cs-btn-sm" onClick={addSourceRow} style={{ marginBottom: 16 }}>
        <Plus size={13} /> Add another source
      </button>

      <div>
        <button type="button" className="cs-btn cs-btn-primary" onClick={submit} disabled={busy || !name.trim()}>
          {busy ? <Loader2 size={15} className="cs-spin" /> : <Plus size={15} />}
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

/** Single-row variant for adding one more source to an already-existing
 *  competitor — inline on that competitor's card/row. */
export function AddSourceRow({ onSubmit, busy }) {
  const [row, setRow] = useState(emptySource());
  const [error, setError] = useState('');

  const isTermType = TERM_SOURCE_TYPES.has(row.platform);

  const submit = async () => {
    if (isTermType) {
      if (!row.handle.trim()) {
        setError('Enter a value.');
        return;
      }
    } else if (!isPlausibleUrl(row.url)) {
      setError('Enter a valid URL.');
      return;
    }
    setError('');
    await onSubmit(
      isTermType
        ? { platform: row.platform, url: '', handle: row.handle.trim() }
        : { platform: row.platform, url: row.url.trim(), handle: row.handle.trim() || null },
    );
    setRow(emptySource());
  };

  return (
    <div>
      <div className="cs-source-row">
        <select className="cs-select" value={row.platform} onChange={(event) => setRow({ ...row, platform: event.target.value })}>
          {SOURCE_KIND_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <SourceRowFields row={row} onChange={(patch) => setRow({ ...row, ...patch })} />
        <button
          type="button"
          className="cs-btn cs-btn-sm"
          onClick={submit}
          disabled={busy || (isTermType ? !row.handle.trim() : !row.url.trim())}
        >
          {busy ? <Loader2 size={13} className="cs-spin" /> : <Plus size={13} />} Add
        </button>
      </div>
      {error ? (
        <div className="cs-source-error">
          <AlertTriangle size={12} style={{ marginRight: 4, verticalAlign: -1 }} />
          {error}
        </div>
      ) : null}
    </div>
  );
}
