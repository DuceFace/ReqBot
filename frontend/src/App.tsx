import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import SearchView from './views/SearchView'
import TraceView from './views/TraceView'
import CompareView from './views/CompareView'
import EvidenceView from './views/EvidenceView'
import DocsView from './views/DocsView'
import NotFoundView from './views/NotFoundView'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/search" replace />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/compare" element={<CompareView />} />
        <Route path="/evidence" element={<EvidenceView />} />
        <Route path="/docs" element={<DocsView />} />
        <Route path="/trace/:reqId" element={<TraceView />} />
        <Route path="*" element={<NotFoundView />} />
      </Routes>
    </BrowserRouter>
  )
}
