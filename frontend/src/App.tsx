import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import SearchView from './views/SearchView'
import TraceView from './views/TraceView'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/search" replace />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/trace/:reqId" element={<TraceView />} />
      </Routes>
    </BrowserRouter>
  )
}
