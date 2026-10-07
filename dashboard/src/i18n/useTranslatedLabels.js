/**
 * Locale-rendered labels for open-ended values the API returns as-is
 * (free-text demographic buckets, survey metadata) - the values no
 * translation catalog can cover. Backed by POST /api/i18n/labels, which
 * translates through the configured LLM and caches server-side.
 *
 * Every component on a page asks for its own values, so requests are
 * queued and flushed together on the next tick (one call per page render
 * rather than one per chart/row), and results are cached per locale for the
 * life of the page. Nothing is requested for the default locale - those
 * values already are in it. Until a label arrives (or if it can't be
 * translated), callers get null and show their own fallback.
 */
import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';

import { translateLabels } from '../api/i18nApi.js';
import { DEFAULT_LOCALE } from './locales.js';

// Server-side cap per request (label_translation.MAX_LABELS_PER_REQUEST).
const MAX_VALUES_PER_REQUEST = 200;
const EMPTY = new Map();

const cache = new Map(); // locale -> Map(value -> label), replaced on update
const requested = new Map(); // locale -> Set of values queued, in flight, or done
const queue = new Map(); // locale -> Set of values awaiting the next flush
const listeners = new Set();
let flushScheduled = false;

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function store(locale, labels) {
  const next = new Map(cache.get(locale) || EMPTY);
  for (const [value, label] of Object.entries(labels)) next.set(value, label);
  cache.set(locale, next);
  listeners.forEach((listener) => listener());
}

async function flush() {
  flushScheduled = false;
  const pending = [...queue.entries()];
  queue.clear();
  for (const [locale, values] of pending) {
    const list = [...values];
    for (let start = 0; start < list.length; start += MAX_VALUES_PER_REQUEST) {
      const chunk = list.slice(start, start + MAX_VALUES_PER_REQUEST);
      let labels;
      try {
        labels = await translateLabels(locale, chunk);
      } catch {
        labels = {};
      }
      const translated = {};
      for (const value of chunk) {
        const label = labels[value];
        if (typeof label === 'string' && label.trim() && label !== value) {
          translated[value] = label;
        } else {
          // Not translated this time (provider down, or an unchanged
          // label) - let a later mount ask again rather than caching the
          // miss for the rest of the session.
          requested.get(locale)?.delete(value);
        }
      }
      if (Object.keys(translated).length) store(locale, translated);
    }
  }
}

function enqueue(locale, values) {
  if (!requested.has(locale)) requested.set(locale, new Set());
  const seen = requested.get(locale);
  for (const value of values) {
    if (seen.has(value)) continue;
    seen.add(value);
    if (!queue.has(locale)) queue.set(locale, new Set());
    queue.get(locale).add(value);
  }
  if (queue.size && !flushScheduled) {
    flushScheduled = true;
    setTimeout(flush, 0);
  }
}

function normalizeValues(values) {
  const distinct = new Set();
  for (const value of values || []) {
    const text = typeof value === 'string' ? value.trim() : '';
    if (text) distinct.add(text);
  }
  return [...distinct].sort();
}

/**
 * Returns `labelFor(value)` - the translated label for one of `values` in
 * the active locale, or null when there isn't one (yet).
 */
export function useTranslatedLabels(values) {
  const { i18n } = useTranslation();
  const locale = i18n.language;
  const key = JSON.stringify(normalizeValues(values));
  const labels = useSyncExternalStore(subscribe, () => cache.get(locale) || EMPTY);

  useEffect(() => {
    if (locale === DEFAULT_LOCALE) return;
    const list = JSON.parse(key);
    if (list.length) enqueue(locale, list);
  }, [locale, key]);

  return useCallback((value) => {
    if (locale === DEFAULT_LOCALE || typeof value !== 'string') return null;
    return labels.get(value.trim()) || null;
  }, [locale, labels]);
}

// Test hook: forget every cached/requested label.
export function resetTranslatedLabelsCache() {
  cache.clear();
  requested.clear();
  queue.clear();
  flushScheduled = false;
}
