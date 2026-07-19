import type { ReactNode } from 'react'
import SidebarNav from './SidebarNav'

interface Props {
  children: ReactNode
}

export default function AppShell({ children }: Props) {
  return (
    <div className="flex min-h-screen">
      <SidebarNav />
      <div className="flex-1 min-w-0 bg-gray-50">
        {children}
      </div>
    </div>
  )
}
