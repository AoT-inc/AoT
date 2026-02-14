import { useQuery } from '@tanstack/react-query'
import { fetchNotes } from '../lib/api'
import { FileText, Download, X as CloseIcon, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { createPortal } from 'react-dom'
import { useState, useRef, useEffect } from 'react'

export default function NotesList({ target }) {
  const [galleryState, setGalleryState] = useState(null) // { mediaFiles: [], index: 0 }
  const { data: notes, isLoading, error } = useQuery({
    queryKey: ['notes', target.targetId],
    queryFn: () => fetchNotes(target.targetId),
    refetchInterval: 5000 
  })

  if (isLoading) return (
     <div className="flex flex-col items-center justify-center py-10 text-slate-500">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mb-2"></div>
        <p className="text-xs">Loading...</p>
     </div>
  )

  if (error) return (
     <div className="p-4 mx-4 bg-red-500/10 text-red-400 rounded-lg text-xs text-center border border-red-500/20">
        Failed to load notes.
     </div>
  )

  if (!notes || notes.length === 0) return (
     <div className="flex flex-col items-center justify-center py-20 text-slate-600 opacity-50">
        <FileText size={48} strokeWidth={1} />
        <p className="mt-2 text-sm">No recorded notes found.</p>
     </div>
  )

  return (
    <div className="space-y-4">
        {notes.map((note) => (
            <NoteItem 
                key={note.unique_id}
                note={note} 
                onDelete={() => deleteMutation.mutate(note.unique_id)}
                onUpdate={(updatedData) => updateMutation.mutate({ unique_id: note.unique_id, ...updatedData })}
                onOpenGallery={(mediaFiles, index) => setGalleryState({ mediaFiles, index })}
            />
        ))}

        {galleryState && (
            <GalleryOverlay 
                mediaFiles={galleryState.mediaFiles} 
                initialIndex={galleryState.index} 
                onClose={() => setGalleryState(null)} 
            />
        )}
    </div>
  )
}

const NoteItem = ({ note, onDelete, onUpdate, onOpenGallery }) => {
    const files = note.files ? note.files.split(',').map(f => f.trim()).filter(f => f !== '') : []
    const noteDate = new Date(note.date_time);
    const [selectedImage, setSelectedImage] = useState(null);

    // Filter images/videos
    const mediaFiles = files.filter(f => /\.(jpg|jpeg|png|gif|webp|bmp|heic|mp4|webm|mov)$/i.test(f));
    
    useEffect(() => {
        if (mediaFiles.length > 0 && !selectedImage) {
            setSelectedImage(mediaFiles[0]);
        }
    }, [mediaFiles, selectedImage]);

    const otherFiles = files.filter(f => !mediaFiles.includes(f));

    const handleMainClick = (e) => {
        e.stopPropagation();
        const idx = mediaFiles.indexOf(selectedImage);
        onOpenGallery(mediaFiles, idx !== -1 ? idx : 0);
    };

    return (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow group">
             {/* Note Header */}
             <div className="px-4 py-2 bg-slate-50/50 border-b border-slate-100 flex items-center justify-between">
                 <div className="flex items-center gap-2">
                     <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">{note.user || 'User'}</span>
                 </div>
                 <span className="text-[10px] text-slate-400 font-medium">
                    {formatDistanceToNow(noteDate, { addSuffix: true })}
                 </span>
             </div>
             
             {/* Note Content */}
             <div className="p-4 space-y-3">
                 {note.note && (
                    <div className="text-slate-800 text-sm leading-relaxed">
                        <NoteTextContent text={note.note} />
                    </div>
                 )}

                  {mediaFiles.length > 0 && (
                      <div className="space-y-3">
                         {/* Main Media Preview in Card */}
                         <div className="w-full">
                             <MediaItem 
                                 file={selectedImage}
                                 onClick={handleMainClick}
                                 isMain={true} 
                             />
                         </div>
                         
                         {/* Thumbnails if > 1 */}
                         {mediaFiles.length > 1 && (
                             <div className="relative group/thumbs">
                                 <ThumbnailList 
                                     mediaFiles={mediaFiles} 
                                     activeIndex={mediaFiles.indexOf(selectedImage)}
                                     onThumbClick={(index) => setSelectedImage(mediaFiles[index])}
                                 />
                             </div>
                         )}
                      </div>
                  )}

                 {otherFiles.length > 0 && (
                     <div className="flex flex-col gap-1.5 pt-1">
                        {otherFiles.map((file, i) => (
                            <FileAttachment key={i} file={file} />
                        ))}
                     </div>
                 )}
             </div>
        </div>
    )
}

import { TransformWrapper, TransformComponent } from "react-zoom-pan-pinch";

function GalleryOverlay({ mediaFiles, initialIndex, onClose }) {
    const [currentIndex, setCurrentIndex] = useState(initialIndex);
    const touchStartX = useRef(0);
    const touchEndX = useRef(0);

    const next = () => setCurrentIndex((prev) => (prev + 1) % mediaFiles.length);
    const prev = () => setCurrentIndex((prev) => (prev - 1 + mediaFiles.length) % mediaFiles.length);

    // Basic Swipe for navigating between images if not zoomed? 
    // Implementing swipe with zoom library might conflict. 
    // Let's rely on buttons mostly or careful event handling.
    // For now, keeping buttons as primary nav.

    const currentFile = mediaFiles[currentIndex];
    const fullPath = currentFile ? currentFile.trim() : "";
    const filenameOnly = fullPath.includes('/') ? fullPath.split('/').pop() : fullPath;
    const isImage = /\.(jpg|jpeg|png|gif|webp|bmp|heic)$|_(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(filenameOnly);
    const url = `/note_attachment/${fullPath}`;

    return createPortal(
        <div 
            className="fixed inset-0 z-[50000] flex flex-col bg-black/95 animate-in fade-in duration-300 overflow-hidden"
            onClick={onClose}
        >
            {/* Header / Close */}
            <div className="absolute top-0 left-0 right-0 p-4 flex justify-between items-center z-[50002] bg-gradient-to-b from-black/60 to-transparent pointer-events-none">
                <span className="text-white text-sm font-medium px-4 py-2 bg-black/40 rounded-full pointer-events-auto">
                    {currentIndex + 1} / {mediaFiles.length}
                </span>
                <button 
                    className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors pointer-events-auto"
                    onClick={onClose}
                >
                    <CloseIcon size={24} />
                </button>
            </div>

            {/* Desktop Nav Arrows - Fixed Position Relative to Viewport */}
            {mediaFiles.length > 1 && (
                <>
                    <button 
                        onClick={(e) => { e.stopPropagation(); prev(); }}
                        className="absolute left-4 top-1/2 -translate-y-1/2 z-[50002] p-3 text-white/50 hover:text-white bg-black/20 hover:bg-black/40 rounded-full transition-all md:block"
                    >
                        <ChevronLeft size={40} />
                    </button>
                    <button 
                        onClick={(e) => { e.stopPropagation(); next(); }}
                        className="absolute right-4 top-1/2 -translate-y-1/2 z-[50002] p-3 text-white/50 hover:text-white bg-black/20 hover:bg-black/40 rounded-full transition-all md:block"
                    >
                        <ChevronRight size={40} />
                    </button>
                </>
            )}

            {/* Content Area */}
            <div className="w-full h-full flex items-center justify-center p-0" onClick={e => e.stopPropagation()}>
                {isImage ? (
                    <TransformWrapper
                        initialScale={1}
                        minScale={1}
                        maxScale={4}
                        centerOnInit={true}
                        wheel={{ step: 0.2 }}
                    >
                        {({ zoomIn, zoomOut, resetTransform, ...rest }) => (
                            <TransformComponent
                                wrapperClass="!w-full !h-full flex items-center justify-center"
                                contentClass="!w-full !h-full flex items-center justify-center"
                            >
                                <img 
                                    src={url} 
                                    key={url} // Reset transform on image change if handled by wrapper
                                    alt="Full view" 
                                    className="max-w-[100vw] max-h-[100vh] object-contain" 
                                />
                            </TransformComponent>
                        )}
                    </TransformWrapper>
                ) : (
                    <video src={url} key={url} controls autoPlay className="max-w-full max-h-full" />
                )}
            </div>
        </div>,
        document.body
    );
}

function ThumbnailList({ mediaFiles, activeIndex, onThumbClick, className = "" }) {
    const scrollRef = useRef(null);

    const scroll = (direction) => {
        if (scrollRef.current) {
            const amount = direction === 'left' ? -160 : 160;
            scrollRef.current.scrollBy({ left: amount, behavior: 'smooth' });
        }
    };

    return (
        <div className={`relative flex items-center ${className}`}>
            <button 
                onClick={(e) => { e.stopPropagation(); scroll('left'); }}
                className="absolute left-0 z-10 p-1 bg-white/80 rounded-full shadow-md text-slate-700 opacity-0 group-hover/thumbs:opacity-100 transition-opacity translate-x-1"
            >
                <ChevronLeft size={16} />
            </button>
            <div 
                ref={scrollRef}
                className="flex gap-2 overflow-x-auto pb-1 no-scrollbar scroll-smooth w-full px-1"
            >
                {mediaFiles.map((file, i) => (
                    <button
                        key={i}
                        onClick={(e) => { e.stopPropagation(); onThumbClick(i); }}
                        className={`block flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden border-2 transition-all ${i === activeIndex ? 'border-blue-500 scale-95 shadow-inner' : 'border-transparent opacity-70 hover:opacity-100'}`}
                    >
                        <MediaPreview file={file} />
                    </button>
                ))}
            </div>
            <button 
                onClick={(e) => { e.stopPropagation(); scroll('right'); }}
                className="absolute right-0 z-10 p-1 bg-white/80 rounded-full shadow-md text-slate-700 opacity-0 group-hover/thumbs:opacity-100 transition-opacity -translate-x-1"
            >
                <ChevronRight size={16} />
            </button>
        </div>
    );
}

function MediaPreview({ file }) {
    const fullPath = file ? file.trim() : "";
    const filenameOnly = fullPath.includes('/') ? fullPath.split('/').pop() : fullPath;
    const isImage = /\.(jpg|jpeg|png|gif|webp|bmp|heic)$|_(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(filenameOnly);
    const url = `/note_attachment/${fullPath}`

    if (isImage) {
        return <img src={url} alt="thumb" className="w-full h-full object-cover" loading="lazy" />;
    }
    return (
        <div className="w-full h-full bg-slate-900 flex items-center justify-center text-white text-[8px]">
            VIDEO
        </div>
    );
}

function MediaItem({ file, onClick, isMain = false }) {
    const fullPath = file ? file.trim() : "";
    const filenameOnly = fullPath.includes('/') ? fullPath.split('/').pop() : fullPath;
    const isImage = /\.(jpg|jpeg|png|gif|webp|bmp|heic)$|_(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(filenameOnly);
    const isVideo = /\.(mp4|webm|mov)$|_(mp4|webm|mov)$/i.test(filenameOnly);
    const url = `/note_attachment/${fullPath}`

    if (isImage) {
        return (
            <div 
                onClick={onClick}
                className="block relative group rounded-xl overflow-hidden border border-slate-200 hover:border-blue-400 transition-all bg-slate-100 cursor-zoom-in"
            >
                <img 
                    src={url} 
                    alt="attachment" 
                    className="w-full h-[400px] object-cover transition-transform duration-300 group-hover:scale-105" 
                    loading="lazy" 
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors pointer-events-none" />
            </div>
        )
    }

    if (isVideo) {
        return (
            <div className="rounded-xl overflow-hidden border border-slate-200 bg-black w-full" onClick={onClick}>
                <video 
                    src={url} 
                    controls={true} 
                    preload="metadata" 
                    className="w-full max-h-[400px]" 
                />
            </div>
        )
    }

    return null;
}


function FileAttachment({ file }) {
    const fullPath = file ? file.trim() : "";
    const filenameOnly = fullPath.includes('/') ? fullPath.split('/').pop() : fullPath;
    const displayName = filenameOnly.length > 37 ? filenameOnly.slice(37) : filenameOnly;
    const url = `/note_attachment/${fullPath}`

    return (
        <a href={url} target="_blank" download className="flex items-center gap-2 p-2 px-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg text-[11px] text-slate-600 transition-colors max-w-full group">
            <div className="bg-white p-1 rounded text-slate-400 group-hover:text-blue-500 shadow-sm transition-colors border border-slate-100">
                <Download size={12} />
            </div>
            <span className="truncate flex-1 font-medium">{displayName}</span>
        </a>
    )
}

function NoteTextContent({ text }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const [isOverflowing, setIsOverflowing] = useState(false);
    const textRef = useRef(null);

    useEffect(() => {
        if (textRef.current) {
            const el = textRef.current;
            if (el.scrollHeight > el.clientHeight + 1) {
                setIsOverflowing(true);
            }
        }
    }, [text]);

    return (
        <div className="relative">
            <p 
                ref={textRef}
                className={`whitespace-pre-wrap break-words font-medium transition-all duration-300 ${
                    isExpanded ? '' : 'line-clamp-3 overflow-hidden text-ellipsis'
                }`}
            >
                {text}
            </p>
            {isOverflowing && !isExpanded && (
                <button 
                    onClick={(e) => { e.stopPropagation(); setIsExpanded(true); }}
                    className="mt-1 text-xs text-blue-500 hover:text-blue-700 font-medium flex items-center gap-0.5"
                >
                    See more <ChevronRight size={12} />
                </button>
            )}
            {isExpanded && (
                <button 
                    onClick={(e) => { e.stopPropagation(); setIsExpanded(false); }}
                    className="mt-1 text-xs text-slate-500 hover:text-slate-700 font-medium flex items-center gap-0.5 ml-auto"
                >
                    Collapse <ChevronUp size={12} />
                </button>
            )}
        </div>
    );
}
