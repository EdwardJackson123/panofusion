import { Routes, Route } from 'react-router-dom'
import ProjectPage from './pages/ProjectPage'
import ViewerPage from './pages/ViewerPage'

export default function App() {
  return (
    <div className="min-h-screen bg-near-black text-white">
      <Routes>
        <Route path="/" element={<ProjectPage />} />
        <Route path="/viewer/:projectName" element={<ViewerPage />} />
      </Routes>
    </div>
  )
}
