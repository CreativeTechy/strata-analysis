import { createContext, useContext } from 'react';

/**
 * The project whose documents the labels on screen came from. Display-label
 * translations are cached and authorized per project server-side
 * (POST /api/i18n/labels), so useTranslatedLabels() asks on behalf of this
 * one and makes no request when there isn't one.
 */
const LabelProjectContext = createContext(null);

export const LabelProjectProvider = LabelProjectContext.Provider;

export function useLabelProjectId() {
  return useContext(LabelProjectContext);
}
