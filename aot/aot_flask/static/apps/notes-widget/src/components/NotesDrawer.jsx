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
            // Desktop: fixed 400px panel pinned to the right edge. The page is
            // pushed left by body.notes-drawer-active (see the scroll-lock effect),
            // so the drawer sits BESIDE the page — same frame-split as the AI chat.
            setViewportStyle({
                position: 'fixed',
                top: 0,
                right: 0,
                height: '100%',
                left: 'auto',
                bottom: 'auto',
                width: '400px'
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
    const DESKTOP = window.innerWidth >= 768;

    // Restore everything (desktop push class + mobile fixed-lock).
    const restore = () => {
        document.body.classList.remove('notes-drawer-active');
        const storedScrollY = document.body.dataset.aotScrollY;
        if (storedScrollY !== undefined) {
            document.body.style.position = '';
            document.body.style.top = '';
            document.body.style.width = '';
            document.body.style.overflow = '';
            window.scrollTo(0, parseInt(storedScrollY));
            delete document.body.dataset.aotScrollY;
        }
    };

    if (isOpen) {
        if (!DESKTOP) {
            // Mobile: physically lock the background (position:fixed) so the soft
            // keyboard can't scroll/overshoot the document behind the sheet.
            const scrollY = window.scrollY;
            document.body.style.position = 'fixed';
            document.body.style.top = `-${scrollY}px`;
            document.body.style.width = '100%';
            document.body.style.overflow = 'hidden';
            document.body.dataset.aotScrollY = scrollY.toString();
        } else if (isGlobal) {
            // Desktop + dashboard/map (portaled to body): push the page left so the
            // drawer sits beside it (frame split, like the AI chat). Page stays
            // scrollable. Let widgets reflow after the 0.4s padding transition.
            document.body.classList.add('notes-drawer-active');
            setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
        }
        // Desktop + in-modal: the host modal owns the layout — no body change.
    } else {
        restore();
        setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
    }

    // Cleanup on unmount (emergency restore)
    return () => { restore(); };
  }, [isOpen, isGlobal]);

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
      {/* Drawer — shell shared with the AI chat via .aot-drawer* classes (aot-drawer.css) */}
      <div className="aot-drawer active relative w-full h-full flex flex-col" style={{ position: 'relative', right: 'auto' }}>

        {/* Header */}
        <div className="aot-drawer-header">
            <div className="min-w-0 pr-2">
                <h2 className="aot-drawer-title-text">{target.name || 'Notes'}</h2>
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
                className="aot-icon-btn"
                aria-label="Close"
            >
                <X size={22} />
            </button>
        </div>

        {/* Content Area (List) */}
        <div className="aot-drawer-body">
             <NotesList target={target} />
        </div>

        {/* Input Area with Dynamic Padding */}
        <div
            className="aot-drawer-footer safe-area-bottom shadow-[0_-5px_15px_rgba(0,0,0,0.03)]"
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
