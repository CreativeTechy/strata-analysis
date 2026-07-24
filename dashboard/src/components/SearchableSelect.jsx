import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';

// Single-select combobox: type to filter, click/enter to choose. Always keeps
// an "All ..." option pinned at the top so callers can offer an aggregate view
// alongside a searchable list (sources, keywords, etc.) without a separate control.
export default function SearchableSelect({ label, icon, value, options, onChange, allLabel = 'All', placeholder = 'Search…', disabled = false }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef(null);
  const inputId = useId();

  const allOption = { value: 'all', label: allLabel };
  const allOptions = [allOption, ...options];
  const selected = allOptions.find((option) => String(option.value) === String(value)) || allOption;

  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  useEffect(() => {
    function handlePointerDown(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, []);

  const needle = query.trim().toLowerCase();
  const filtered = needle ? allOptions.filter((option) => option.label.toLowerCase().includes(needle)) : allOptions;

  const choose = (option) => {
    onChange(option.value);
    setOpen(false);
  };

  return (
    <div className={`searchable-select${disabled ? ' is-disabled' : ''}`} ref={containerRef}>
      {label && (
        <label className="searchable-select-label" htmlFor={inputId}>
          {icon}
          {label}
        </label>
      )}
      <div className="searchable-select-control">
        <Search size={14} aria-hidden="true" />
        <input
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          autoComplete="off"
          disabled={disabled}
          value={open ? query : selected.label}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && filtered.length === 1) {
              choose(filtered[0]);
            } else if (event.key === 'Escape') {
              setOpen(false);
            }
          }}
        />
        <ChevronDown size={14} aria-hidden="true" className={`searchable-select-caret${open ? ' is-open' : ''}`} />
      </div>
      {open && (
        <ul className="searchable-select-list" role="listbox">
          {filtered.length ? (
            filtered.map((option) => (
              <li key={option.value} role="option" aria-selected={String(option.value) === String(value)}>
                <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option)}>
                  {option.label}
                </button>
              </li>
            ))
          ) : (
            <li className="searchable-select-empty">No matches</li>
          )}
        </ul>
      )}
    </div>
  );
}
