import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// Without vitest's `globals: true` (deliberately not set — explicit
// imports are clearer than ambient globals), @testing-library/react's
// automatic per-test cleanup can't detect a global afterEach, so it's
// wired up explicitly here instead. Without this, DOM from one test
// leaks into the next within the same file.
afterEach(() => {
  cleanup()
})
