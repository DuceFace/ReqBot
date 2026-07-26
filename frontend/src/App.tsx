import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import SearchView from './views/SearchView'
import TraceView from './views/TraceView'
import CompareView from './views/CompareView'
import EvidenceView from './views/EvidenceView'
import CorpusView from './views/CorpusView'
import CorpusDetailView from './views/CorpusDetailView'
import SystemView from './views/SystemView'
import SettingsView from './views/SettingsView'
import ChecklistsView from './views/ChecklistsView'
import ChecklistPreviewView from './views/ChecklistPreviewView'
import NotFoundView from './views/NotFoundView'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/search" replace />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/compare" element={<CompareView />} />
        <Route path="/evidence" element={<EvidenceView />} />
        <Route path="/corpus" element={<CorpusView />} />
        <Route path="/corpus/:docId" element={<CorpusDetailView />} />
        <Route path="/system" element={<SystemView />} />
        <Route path="/settings" element={<SettingsView />} />
        <Route path="/checklists" element={<ChecklistsView />} />
        <Route path="/checklists/:docId" element={<ChecklistPreviewView />} />
        {/* Redirect legacy /docs bookmarks to /corpus */}
        <Route path="/docs" element={<Navigate to="/corpus" replace />} />
        <Route path="/trace/:reqId" element={<TraceView />} />
        <Route path="*" element={<NotFoundView />} />
      </Routes>
    </BrowserRouter>
  )
}
