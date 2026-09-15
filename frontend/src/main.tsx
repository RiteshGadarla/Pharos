import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Three pages: the landing page at /, the operator console at /run and the
// image inspector at /inspect. Each is loaded on demand so a page load
// only ever pulls in that page's stylesheet; the pages share class names
// (.brand, .status, ...) and would clash otherwise. Links between them are
// plain full page loads.
const path = window.location.pathname.replace(/\/+$/, '')

const page =
  path === '/run'
    ? import('./App.tsx')
    : path === '/inspect'
      ? import('./inspect/Inspect.tsx')
      : import('./landing/Landing.tsx')

page.then(({ default: Page }) => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Page />
    </StrictMode>,
  )
})
