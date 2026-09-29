import { cleanup, configure } from '@testing-library/react'
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

// Maps load lazily (components/LazyMapView.tsx), and the first import of
// Leaflet in a test file can take over the default 1 s under a full-suite
// load. A longer wait for findBy*/waitFor keeps those tests from flaking;
// it only matters when something is genuinely slow.
configure({ asyncUtilTimeout: 5000 })
