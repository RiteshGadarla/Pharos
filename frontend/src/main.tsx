import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Two pages: the landing page at / and the operator console at /run. Each
// is loaded on demand so a page load only ever pulls in that page's
// stylesheet; the two share class names (.brand, .status, ...) and would
// clash otherwise. Links between them are plain full page loads.
const path = window.location.pathname.replace(/\/+$/, '')

const page = path === '/run' ? import('./App.tsx') : import('./landing/Landing.tsx')

page.then(({ default: Page }) => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Page />
    </StrictMode>,
  )
})
