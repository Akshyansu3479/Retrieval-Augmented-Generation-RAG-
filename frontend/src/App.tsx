import { useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { DocumentPanel } from './components/DocumentPanel'
import { StatusBar } from './components/StatusBar'
import './App.css'

export default function App() {
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  return (
    <div className="app-shell">
      <StatusBar />
      <main className="workspace">
        <DocumentPanel
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
        />
        <ChatPanel selectedIds={selectedIds} />
      </main>
    </div>
  )
}
