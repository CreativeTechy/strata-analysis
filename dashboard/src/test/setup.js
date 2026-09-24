import { beforeEach } from 'vitest'

import '@testing-library/jest-dom/vitest'

// Node's built-in Web Storage shadows jsdom's window.localStorage (Node 22+),
// so tests need their own mock rather than relying on jsdom to provide one.
const values = new Map()
const localStorageMock = {
  getItem: (key) => values.get(String(key)) ?? null,
  setItem: (key, value) => values.set(String(key), String(value)),
  removeItem: (key) => values.delete(String(key)),
  clear: () => values.clear(),
  key: (index) => [...values.keys()][index] ?? null,
  get length() { return values.size },
}

Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: localStorageMock,
})

// Every component using useTranslation() needs a configured i18next
// instance - react-i18next resolves it globally (no <I18nextProvider> is
// required) as long as `.init()` has run somewhere in the module graph
// before a component renders, so this one import here covers every test
// file. Reset to English before each test regardless of what a
// locale-switching test in one file left behind in the shared i18next
// singleton or in jsdom's localStorage - test order must not matter.
import i18n from '../i18n/index.js'

beforeEach(async () => {
  localStorageMock.clear()
  if (i18n.language !== 'en') {
    await i18n.changeLanguage('en')
  }
  document.documentElement.lang = 'en'
  document.documentElement.dir = 'ltr'
})
