import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import NotesDrawer from './components/NotesDrawer'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient()

function App() {
  const [isOpen, setIsOpen] = useState(false)
  const [target, setTarget] = useState(null)
  const [injectionTarget, setInjectionTarget] = useState({ element: null, isGlobal: false })

  // Hybrid Target Detection: Find visible modal OR fallback to document.body
  const findInjectionTarget = () => {
    const modals = Array.from(document.querySelectorAll('.modal'));
    const activeModal = modals.find(m => {
        const style = window.getComputedStyle(m);
        return style.display !== 'none' && (m.classList.contains('show') || style.opacity > "0");
    });
    
    if (activeModal) {
        const content = activeModal.querySelector('.modal-content');
        if (content) return { element: content, isGlobal: false };
    }
    
    // Fallback: Use body if no active modal is found (Dashboard/Map mode)
    return { element: document.body, isGlobal: true };
  };

  useEffect(() => {
    const handleOpen = (e) => {
      console.log("[AoT Notes] Open event received", e.detail);
      if (e.detail) {
        setTarget(e.detail)
        setIsOpen(true)
        setInjectionTarget(findInjectionTarget());
      }
    }

    const handleClose = () => {
        setIsOpen(false);
        setInjectionTarget({ element: null, isGlobal: false });
        window.dispatchEvent(new CustomEvent('notes-closed'));
    }

    window.addEventListener('open-notes', handleOpen)
    window.addEventListener('close-notes', handleClose)
    
    // Observer handles dynamic appearance of modals
    const observer = new MutationObserver(() => {
        if (isOpen && (!injectionTarget.element || injectionTarget.isGlobal)) {
            const nextTarget = findInjectionTarget();
            // Upgrade from Global (body) to Modal if a modal suddenly appears
            if (nextTarget.element && !nextTarget.isGlobal) {
                console.log("[AoT Notes] Upgrading to Modal Portal");
                setInjectionTarget(nextTarget);
            }
        }
    });

    observer.observe(document.body, { 
        childList: true, 
        subtree: true, 
        attributes: true, 
        attributeFilter: ['class', 'style'] 
    });

    return () => {
        window.removeEventListener('open-notes', handleOpen)
        window.removeEventListener('close-notes', handleClose)
        observer.disconnect();
    }
  }, [isOpen, injectionTarget])

  const renderContent = () => {
    if (!target) return null;
    return (
      <NotesDrawer 
          isOpen={isOpen}
          target={target} 
          isGlobal={injectionTarget.isGlobal}
          onClose={() => setIsOpen(false)} 
      />
    );
  };

  return (
    <QueryClientProvider client={queryClient}>
        {isOpen && injectionTarget.element ? createPortal(renderContent(), injectionTarget.element) : null}
        
        {/* Dev Mode Trigger */}
        {import.meta.env.DEV && (
            <div className="fixed bottom-4 right-4 pointer-events-auto z-50 flex gap-2">
                <button 
                    className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg shadow-lg" 
                    onClick={() => {
                        setTarget({ targetId: 'test-global', targetType: 'site', name: 'Global Note' });
                        setIsOpen(true);
                        setInjectionTarget(findInjectionTarget());
                    }}
                >
                    Test Global
                </button>
            </div>
        )}
    </QueryClientProvider>
  )
}

export default App
