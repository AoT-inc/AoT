import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import NotesList from './NotesList'
import NotesInput from './NotesInput'

export default function NotesDrawer({ isOpen, target, isGlobal, onClose }) {

  // Phase 4: Full Layout Stabilization Strategy
  // Use fixed positioning for the drawer to stop it from moving/overshooting.
  // Use dynamic padding on the input container to handle keyboard + extra spacing.
  const [viewportStyle, setViewportStyle] = useState({});
  const [inputPadding, setInputPadding] = useState(0);

  useEffect(() => {
    // Only apply on mobile/visualViewport supported browsers for special handling
    if (!window.visualViewport) return;

    const handleResize = () => {
        const isMobile = window.innerWidth < 768;

        if (isMobile) {
            // Mobile Phase 4:
            // 1. Lock Drawer to full screen (inset: 0). Do NOT change height/top dynamically to avoid jitter.
            setViewportStyle({
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0, // Full screen
                height: '100%', // Full height
                width: '100%'
            });

            // 2. Calculate dynamic padding for the Input Area.
            // Formula: (Keyboard Height) + 300px (User Request)
            // Keyboard Height = window.innerHeight - window.visualViewport.height
            // Phase 5: Add Threshold (>150px) to prevent false positives on load
            const heightDiff = window.innerHeight - window.visualViewport.height;
            const isKeyboardOpen = heightDiff > 150; // Threshold to detect soft keyboard

            if (isKeyboardOpen) {
                 setInputPadding(heightDiff + 300);
            } else {
                 setInputPadding(0);
            }

        } else {
            // Desktop: Restore default right-aligned layout
            setViewportStyle({
                position: 'fixed',
                top: 0,
                right: 0,
                height: '100%',
                left: 'auto', 
                bottom: 'auto',
                width: '' // Let CSS handle it
            });
            setInputPadding(0); // Reset padding on desktop
        }
    };

    window.visualViewport.addEventListener('resize', handleResize);
    window.visualViewport.addEventListener('scroll', handleResize);
    window.addEventListener('resize', handleResize);
    
    // Initial Setting
    handleResize();

    return () => {
        window.visualViewport.removeEventListener('resize', handleResize);
        window.visualViewport.removeEventListener('scroll', handleResize);
        window.removeEventListener('resize', handleResize);
    };
  }, []);

  // Phase 7: Aggressive Body Scroll Lock
  // Prevents the background document from scrolling/overshooting when the virtual keyboard activates.
  useEffect(() => {
    if (isOpen) {
        const scrollY = window.scrollY;
        
        // Lock body
        // We set position fixed to physically prevent the browser from scrolling the document
        // which causes the "overshoot" when the keyboard tries to scroll the input into view.
        document.body.style.position = 'fixed';
        document.body.style.top = `-${scrollY}px`;
        document.body.style.width = '100%';
        document.body.style.overflow = 'hidden';
        
        // Store for restoration
        document.body.dataset.aotScrollY = scrollY.toString();
        
    } else {
        // Unlock and Restore
        const storedScrollY = document.body.dataset.aotScrollY;
        if (storedScrollY) {
            document.body.style.position = '';
            document.body.style.top = '';
            document.body.style.width = '';
            document.body.style.overflow = '';
            window.scrollTo(0, parseInt(storedScrollY));
            delete document.body.dataset.aotScrollY;
        }
    }

    // Cleanup on unmount (emergency restore)
    return () => {
        const storedScrollY = document.body.dataset.aotScrollY;
        // Check if we still have a stored value to clean up
        if (storedScrollY !== undefined) { 
           document.body.style.position = '';
           document.body.style.top = '';
           document.body.style.width = '';
           document.body.style.overflow = '';
           window.scrollTo(0, parseInt(storedScrollY));
           delete document.body.dataset.aotScrollY;
        }
    };
  }, [isOpen]);

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

  // Phase 3: Use React Portal to escape z-index scaling context of parent modals
  return createPortal(
    <div 
        className={containerClasses}
        style={{
            ...viewportStyle,
            overscrollBehavior: 'contain',
            zIndex: 999999 
        }}
    >
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

        {/* Input Area with Dynamic Padding */}
        <div 
            className="border-t border-slate-100 bg-white safe-area-bottom z-10 shadow-[0_-5px_15px_rgba(0,0,0,0.03)]"
            style={{
                paddingBottom: `${inputPadding + 16}px`, // Add base padding (16px/1rem) to dynamic padding
                paddingTop: '1rem',
                paddingLeft: '1rem',
                paddingRight: '1rem',
                transition: 'padding-bottom 0.1s ease-out' // Smooth transition for keyboard movement
            }}
        >
             <NotesInput target={target} />
        </div>
      </div>
    </div>,
    document.body
  )
}
