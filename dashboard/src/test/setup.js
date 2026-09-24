import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'

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

beforeEach(() => {
  localStorageMock.clear()
})
