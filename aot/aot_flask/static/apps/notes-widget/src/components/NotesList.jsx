import { useQuery } from '@tanstack/react-query'
import { fetchNotes } from '../lib/api'
import { FileText, Download, X as CloseIcon, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-react'
import { t, relativeTime } from '../lib/i18n'
import { createPortal } from 'react-dom'
import { useState, useRef, useEffect } from 'react'
import ScheduleFromSelection from './ScheduleFromSelection'
import LinkedSchedule from './LinkedSchedule'

export default function NotesList({ target }) {
  const [galleryState, setGalleryState] = useState(null) // { mediaFiles: [], index: 0 }
  // 지금 고른 구간 { noteId, start, end, text }. 노트 하나에서만 유효하다 —
  // 두 노트에 걸친 선택은 예정 하나로 만들 수 없다(어느 노트에 매달지 정할
  // 근거가 없다).
  const [selection, setSelection] = useState(null)
  const barRef = useRef(null)

  // 본문 밖을 눌러 선택이 풀리면 바도 사라져야 한다. 본문의 mouseup 만 듣던
  // 때는 다른 곳을 눌러 선택이 없어져도 바가 남아, 아무것도 안 골라 놓고
  // "예정으로" 를 누를 수 있었다.
  //
  // 바 **안**을 누른 것은 예외다 — 폼을 채우는 동안 선택은 이미 풀려 있고,
  // 여기서 지우면 저장 직전에 대상이 사라진다.
  useEffect(() => {
    const onUp = (e) => {
      if (barRef.current && barRef.current.contains(e.target)) return
      const sel = window.getSelection && window.getSelection()
      if (!sel || sel.isCollapsed) setSelection(null)
    }
    document.addEventListener('mouseup', onUp)
    document.addEventListener('touchend', onUp)
    return () => {
      document.removeEventListener('mouseup', onUp)
      document.removeEventListener('touchend', onUp)
    }
  }, [])
  const { data: notes, isLoading, error } = useQuery({
    queryKey: ['notes', target.targetId],
    queryFn: () => fetchNotes(target.targetId),
    refetchInterval: 5000 
  })

  if (isLoading) return (
     <div className="flex flex-col items-center justify-center py-10 text-slate-500">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mb-2"></div>
        <p className="text-xs">{t('Loading...')}</p>
     </div>
  )

  if (error) return (
     <div className="p-4 mx-4 bg-red-500/10 text-red-400 rounded-lg text-xs text-center border border-red-500/20">
        {t('Failed to load notes.')}
     </div>
  )

  if (!notes || notes.length === 0) return (
     <div className="flex flex-col items-center justify-center py-20 text-slate-600 opacity-50">
        <FileText size={48} strokeWidth={1} />
        <p className="mt-2 text-sm">{t('No notes written')}</p>
     </div>
  )

  return (
    <div className="flex flex-col min-h-full space-y-4">
        {notes.map((note) => (
            <NoteItem
                key={note.unique_id}
                note={note}
                targetId={target.targetId}
                onOpenGallery={(mediaFiles, index) => setGalleryState({ mediaFiles, index })}
                onSelect={setSelection}
            />
        ))}

        {/* 고른 구간이 있을 때만 나타난다 — 평소 화면은 그대로다. */}
        {selection && selection.text && (
            <ScheduleFromSelection
                barRef={barRef}
                selection={selection}
                targetId={target.targetId}
                onDone={() => {
                    setSelection(null)
                    // 저장 뒤 선택을 남겨 두면 방금 만든 하이라이트 위에
                    // 파란 선택 영역이 겹쳐 무엇이 반영됐는지 안 보인다.
                    const sel = window.getSelection && window.getSelection()
                    if (sel && sel.removeAllRanges) sel.removeAllRanges()
                }}
            />
        )}

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

// 이 드로어에는 노트 삭제·수정이 **없다.** 예전에는 여기에 onDelete/onUpdate 를
// 넘겼는데, 그 핸들러가 부르는 deleteMutation/updateMutation 은 어디에도 선언돼
// 있지 않았고 api.js 에 해당 요청 함수조차 없었다. 부르는 버튼이 없어 터지지
// 않았을 뿐, 삭제 버튼을 다는 순간 ReferenceError 로 목록 전체가 죽는 함정이었다.
// 다시 붙일 때는 api.js 에 요청 함수부터 만들고 useMutation 을 실제로 선언할 것.
// 노트 삭제는 현재 /notes 페이지에서 한다.
const NoteItem = ({ note, targetId, onOpenGallery, onSelect }) => {
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
                     <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">{note.user || t('User')}</span>
                 </div>
                 <span className="text-[10px] text-slate-400 font-medium">
                    {relativeTime(noteDate)}
                 </span>
             </div>
             
             {/* Note Content */}
             <div className="p-4 space-y-3">
                 {note.note && (
                    <div className="text-slate-800 text-sm leading-relaxed">
                        <NoteTextContent
                            text={note.note}
                            links={note.links}
                            onSelect={(sel) => onSelect && onSelect(
                                sel ? { ...sel, noteId: note.unique_id } : null)}
                        />
                    </div>
                 )}

                 {/* 이 노트에 걸린 예정들. 본문에서 사라진 것(고아)도 여기
                     드러난다 — 숨기면 아무도 취소하지 못하는 약속이 남는다. */}
                 <LinkedSchedule links={note.links} targetId={targetId} />

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
                                    alt={t('Full view')} 
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
            {t('Video')}
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

// DOM 선택 → 본문 문자 offset.
//
// Range.toString() 으로 재는 이유는 본문이 **한 덩어리가 아니기 때문**이다 —
// 예정이 걸린 구간은 <mark> 로 쪼개져 있어 텍스트 노드가 여럿이다. 노드를
// 손으로 세면 하이라이트가 하나 늘 때마다 계산이 어긋난다.
function selectionOffsets(rootEl) {
    const sel = window.getSelection && window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const range = sel.getRangeAt(0);
    if (!rootEl.contains(range.commonAncestorContainer)) return null;
    const pre = range.cloneRange();
    pre.selectNodeContents(rootEl);
    pre.setEnd(range.startContainer, range.startOffset);
    const start = pre.toString().length;
    const value = range.toString();
    if (!value.trim()) return null;
    return { start, end: start + value.length, text: value };
}

// 본문을 하이라이트 구간으로 쪼갠다. 겹치는 구간은 뒤엣것을 버린다 — 서버가
// 겹침을 막지는 않지만, 화면에서 두 <mark> 를 겹쳐 그릴 방법이 없다.
function segments(text, links) {
    const spans = (links || [])
        .filter((l) => l.start != null && l.end != null && l.end > l.start)
        .sort((a, b) => a.start - b.start);
    const out = [];
    let cur = 0;
    spans.forEach((l) => {
        if (l.start < cur) return;
        if (l.start > cur) out.push({ text: text.slice(cur, l.start) });
        out.push({ text: text.slice(l.start, l.end), link: l });
        cur = l.end;
    });
    if (cur < text.length) out.push({ text: text.slice(cur) });
    return out;
}

function NoteTextContent({ text, links, onSelect }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const [isOverflowing, setIsOverflowing] = useState(false);
    const textRef = useRef(null);

    // 선택은 mouseup/touchend 에서 읽는다. selectionchange 로 읽으면 드래그
    // 도중 매 프레임 발화해 바가 깜빡인다.
    const readSelection = () => {
        if (!textRef.current || !onSelect) return;
        onSelect(selectionOffsets(textRef.current));
    };

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
                onMouseUp={readSelection}
                onTouchEnd={readSelection}
                className={`whitespace-pre-wrap break-words font-medium transition-all duration-300 ${
                    isExpanded ? '' : 'line-clamp-3 overflow-hidden text-ellipsis'
                }`}
            >
                {segments(text, links).map((seg, i) => (
                    seg.link
                      ? <mark key={seg.link.link_id}
                              className="bg-amber-100 text-inherit rounded-sm px-0.5"
                        >{seg.text}</mark>
                      : <span key={'t' + i}>{seg.text}</span>
                ))}
            </p>
            {isOverflowing && !isExpanded && (
                <button 
                    onClick={(e) => { e.stopPropagation(); setIsExpanded(true); }}
                    className="mt-1 text-xs text-blue-500 hover:text-blue-700 font-medium flex items-center gap-0.5"
                >
                    {t('See more')} <ChevronRight size={12} />
                </button>
            )}
            {isExpanded && (
                <button 
                    onClick={(e) => { e.stopPropagation(); setIsExpanded(false); }}
                    className="mt-1 text-xs text-slate-500 hover:text-slate-700 font-medium flex items-center gap-0.5 ml-auto"
                >
                    {t('Collapse')} <ChevronUp size={12} />
                </button>
            )}
        </div>
    );
}
