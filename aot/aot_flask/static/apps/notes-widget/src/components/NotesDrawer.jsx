import { X } from 'lucide-react'
import { useEffect } from 'react'
import NotesList from './NotesList'
import NotesInput from './NotesInput'

export default function NotesDrawer({ isOpen, target, isGlobal, onClose }) {

  // Close on Escape
  useEffect(() => {
    const handleEsc = (e) => {
        if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [onClose])

  // Determine container classes based on Hybrid state
  const containerClasses = [
    'aot-in-modal-notes-container',
    isOpen ? 'active' : '',
    isGlobal ? 'is-global' : ''
  ].filter(Boolean).join(' ');

  return (
    <div className={containerClasses}>
      {/* Drawer */}
      <div className="relative w-full h-full bg-white flex flex-col shadow-2xl border-l border-slate-200">
        
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-white/80 backdrop-blur-md z-10">
            <div className="min-w-0 pr-2">
                <h2 className="text-lg font-bold text-slate-900 truncate">{target.name || 'Notes'}</h2>
                <div className="flex items-center gap-2 mt-1">
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-blue-50 text-blue-600 border border-blue-100">
                        {target.targetType}
                    </span>
                    <span className="text-[10px] text-slate-400 font-mono truncate" title={target.targetId}>
                        {target.targetId}
                    </span>
                </div>
            </div>
            <button 
                onClick={onClose}
                className="flex-shrink-0 p-2 -mr-2 hover:bg-slate-100 rounded-full text-slate-400 hover:text-slate-900 transition-colors"
                aria-label="Close"
            >
                <X size={22} />
            </button>
        </div>

        {/* Content Area (List) */}
        <div className="flex-1 overflow-y-auto p-4 scrollbar-none bg-slate-50/30">
             <NotesList target={target} />
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-slate-100 bg-white safe-area-bottom z-10 shadow-[0_-5px_15px_rgba(0,0,0,0.03)]">
             <NotesInput target={target} />
        </div>
      </div>
    </div>
  )
}
