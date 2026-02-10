import { useState, useRef, useEffect } from 'react'
import { Camera, Send, X, Paperclip, Loader2, Plus, Image as ImageIcon, Tag, Hash } from 'lucide-react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { createNote, fetchTags } from '../lib/api'

export default function NotesInput({ target }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState([])
  const [selectedTags, setSelectedTags] = useState([])
  const [showMenu, setShowMenu] = useState(false)
  const [showTagInput, setShowTagInput] = useState(false)
  const [newTagText, setNewTagText] = useState('')
  
  const fileInputRef = useRef(null)
  const isSubmitting = useRef(false)
  const queryClient = useQueryClient()
  const textareaRef = useRef(null)

  // Fetch available tags
  const { data: availableTags = [] } = useQuery({
    queryKey: ['availableTags'],
    queryFn: fetchTags
  })

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [text])

  const mutation = useMutation({
    mutationFn: createNote,
    onSuccess: () => {
      setText('')
      setFiles([])
      setSelectedTags([])
      setShowMenu(false)
      setShowTagInput(false)
      isSubmitting.current = false
      if (fileInputRef.current) fileInputRef.current.value = ''
      queryClient.invalidateQueries({ queryKey: ['notes', target.targetId] })
      queryClient.invalidateQueries({ queryKey: ['availableTags'] }) // New tags might have been created
    },
    onError: (err) => {
        isSubmitting.current = false
        alert("Failed to save note: " + err.message)
    }
  })

  const resizeImage = (file, maxWidth = 1920, maxHeight = 1920) => {
    return new Promise((resolve) => {
      if (!file.type.startsWith('image/')) {
        resolve(file);
        return;
      }
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = (event) => {
        const img = new Image();
        img.src = event.target.result;
        img.onload = () => {
          const canvas = document.createElement('canvas');
          let width = img.width;
          let height = img.height;

          if (width > height) {
            if (width > maxWidth) {
              height *= maxWidth / width;
              width = maxWidth;
            }
          } else {
            if (height > maxHeight) {
              width *= maxHeight / height;
              height = maxHeight;
            }
          }

          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, width, height);

          canvas.toBlob((blob) => {
            const resizedFile = new File([blob], file.name, {
              type: file.type,
              lastModified: Date.now(),
            });
            resolve(resizedFile);
          }, file.type, 0.92);
        };
      };
    });
  };

  const handleFileSelect = async (e) => {
    if (e.target.files) {
      const incomingFiles = Array.from(e.target.files);
      
      const LIMIT = 20;
      let filesToProcess = incomingFiles;

      if (files.length + incomingFiles.length > LIMIT) {
        const remainingSpace = LIMIT - files.length;
        if (remainingSpace <= 0) {
          alert(`You can only upload a maximum of ${LIMIT} files.`);
          e.target.value = '';
          return;
        }
        alert(`Maximum ${LIMIT} files allowed. Only the first ${remainingSpace} files will be added.`);
        filesToProcess = incomingFiles.slice(0, remainingSpace);
      }

      const processedFiles = await Promise.all(
        filesToProcess.map(file => resizeImage(file))
      );

      setFiles(prev => [...prev, ...processedFiles]);
      setShowMenu(false);
      // Clear value for same-file re-selection if needed
      e.target.value = '';
    }
  }

  const removeFile = (index) => {
      setFiles(prev => prev.filter((_, i) => i !== index))
  }

  const toggleTag = (tagName) => {
      setSelectedTags(prev => 
          prev.includes(tagName) ? prev.filter(t => t !== tagName) : [...prev, tagName]
      )
  }

  const addNewTag = (e) => {
      if (e) e.preventDefault()
      const cleanTag = newTagText.trim().replace(/\s+/g, '_')
      if (cleanTag && !selectedTags.includes(cleanTag)) {
          setSelectedTags(prev => [...prev, cleanTag])
          setNewTagText('')
      }
  }

  const handleSubmit = (e) => {
    if (e) e.preventDefault()
    
    if (isSubmitting.current || (!text.trim() && files.length === 0)) return
    
    isSubmitting.current = true

    const formData = new FormData()
    formData.append('note', text)
    // Send "Quick Note" as title, backend smart subject logic will handle it
    formData.append('name', 'Quick Note')
    formData.append('target_id', target.targetId)
    formData.append('target_type', target.targetType)
    
    // Combine auto tags and user selected tags
    const autoTags = target.name ? [`widget`, `${target.name}`] : [`widget`];
    const allTags = [...new Set([...autoTags, ...selectedTags])];
    formData.append('tags', allTags.join(','))

    if (target.gps_lat && target.gps_lng) {
        formData.append('gps_lat', target.gps_lat)
        formData.append('gps_lng', target.gps_lng)
    }

    files.forEach(file => {
        formData.append('files', file)
    })

    mutation.mutate(formData)
  }

   const isPending = mutation.isPending

  return (
    <div className="relative">
       {/* Tag & File Menu Popup */}
       {showMenu && (
         <div className="absolute bottom-full left-0 mb-3 bg-white border border-slate-200 rounded-[14px] shadow-xl overflow-hidden animate-in slide-in-from-bottom-2 fade-in duration-200 z-20 min-w-[160px]">
            <div className="flex flex-col">
                <button 
                    type="button" 
                    onClick={() => { setShowTagInput(!showTagInput); setShowMenu(false); }} 
                    className="flex items-center gap-3 p-2.5 hover:bg-slate-50 transition-colors text-slate-700 font-medium text-sm group"
                >
                    <div className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white text-blue-600 group-hover:bg-blue-50 transition-colors shadow-sm">
                        <Tag size={16} />
                    </div>
                    <span>Add Tag</span>
                </button>
                <div className="border-t border-slate-100 my-1"></div>
                <button 
                    type="button" 
                    onClick={() => fileInputRef.current?.click()} 
                    className="flex items-center gap-3 p-2.5 hover:bg-slate-50 transition-colors text-slate-700 font-medium text-sm group"
                >
                    <div className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white text-slate-600 group-hover:bg-slate-100 transition-colors shadow-sm">
                        <Paperclip size={16} />
                    </div>
                    <span>File</span>
                </button>
                <button 
                    type="button" 
                    onClick={() => document.getElementById('camera-input')?.click()} 
                    className="flex items-center gap-3 p-2.5 hover:bg-slate-50 transition-colors text-slate-700 font-medium text-sm group"
                >
                    <div className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white text-slate-600 group-hover:bg-slate-100 transition-colors shadow-sm">
                        <Camera size={16} />
                    </div>
                    <span>Camera</span>
                </button>
                <button 
                    type="button" 
                    onClick={() => document.getElementById('photo-input')?.click()} 
                    className="flex items-center gap-3 p-2.5 hover:bg-slate-50 transition-colors text-slate-700 font-medium text-sm group"
                >
                    <div className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white text-slate-600 group-hover:bg-slate-100 transition-colors shadow-sm">
                        <ImageIcon size={16} />
                    </div>
                    <span>Photo</span>
                </button>
            </div>
         </div>
       )}

       {/* Tag Input Overlay */}
       {showTagInput && (
         <div className="absolute bottom-full left-0 mb-3 bg-white border border-slate-200 rounded-[14px] shadow-xl p-3 animate-in fade-in slide-in-from-bottom-2 duration-200 z-30 min-w-[240px] max-w-full">
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-slate-500 flex items-center gap-1">
                    <Hash size={12} /> Select/Create Tag
                </span>
                <button onClick={() => setShowTagInput(false)} className="text-slate-400 hover:text-slate-600">
                    <X size={14} />
                </button>
            </div>
            
            <div className="flex flex-wrap gap-1.5 mb-3 max-h-32 overflow-y-auto pt-1">
                {availableTags.map(tag => (
                   <button 
                     key={tag.unique_id}
                     onClick={() => toggleTag(tag.name)}
                     className={`px-2 py-1 rounded-full text-[11px] font-medium border transition-all ${
                        selectedTags.includes(tag.name) 
                        ? 'bg-blue-600 border-blue-600 text-white shadow-sm' 
                        : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-slate-300'
                     }`}
                   >
                     #{tag.name}
                   </button>
                ))}
            </div>

            <form onSubmit={addNewTag} className="relative mt-2">
                <input 
                    type="text"
                    value={newTagText}
                    onChange={e => setNewTagText(e.target.value)}
                    placeholder="Enter new tag (Enter)"
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg py-1.5 pl-3 pr-8 text-xs focus:outline-none focus:border-blue-400 focus:bg-white transition-all"
                />
                <button 
                    type="submit"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-blue-500 hover:text-blue-700"
                >
                    <Plus size={16} />
                </button>
            </form>
         </div>
       )}

       {/* Horizontal Scroll Containers for Files & Selected Tags */}
       <div className="flex flex-col gap-1.5 mb-2">
          {/* Selected Tags Display */}
          {selectedTags.length > 0 && (
            <div className="flex gap-1.5 overflow-x-auto py-1 scrollbar-none no-scrollbar">
                {selectedTags.map(tagName => (
                    <div key={tagName} className="flex items-center gap-1 bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full text-[11px] font-bold border border-blue-100 flex-shrink-0 animate-in zoom-in-95 duration-200">
                        #{tagName}
                        <button onClick={() => toggleTag(tagName)} className="hover:text-blue-900 transition-colors">
                            <X size={10} />
                        </button>
                    </div>
                ))}
            </div>
          )}

          {/* File Previews */}
          {files.length > 0 && (
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none no-scrollbar">
                {files.map((file, i) => (
                    <div key={i} className="relative group flex-shrink-0">
                        <div className="h-14 w-14 rounded-xl overflow-hidden border border-slate-200 bg-slate-50 flex items-center justify-center shadow-sm">
                            {file.type.startsWith('image/') ? (
                                <img src={URL.createObjectURL(file)} className="h-full w-full object-cover" alt="preview" />
                            ) : (
                                <span className="text-[9px] text-slate-400 text-center px-1 break-all leading-tight">{file.name}</span>
                            )}
                        </div>
                        <button 
                            type="button"
                            onClick={() => removeFile(i)} 
                            className="absolute -top-1.5 -right-1.5 bg-slate-900 rounded-full p-0.5 text-white shadow-md hover:bg-black transition-colors"
                        >
                            <X size={10} />
                        </button>
                    </div>
                ))}
            </div>
          )}
       </div>

       <form onSubmit={handleSubmit} className="flex gap-2 items-center">
          <button 
            type="button" 
            onClick={() => setShowMenu(!showMenu)} 
            className={`flex-shrink-0 w-10 h-10 rounded-full border transition-all duration-300 flex items-center justify-center ${showMenu ? 'bg-slate-100 text-slate-900 border-slate-300 shadow-inner' : 'bg-white text-slate-400 hover:text-slate-600 border-slate-200 hover:border-slate-300 shadow-sm'}`}
            title="Attach or Tag"
          >
            {showMenu ? <X size={18} /> : <Plus size={20} />}
          </button>

          <input 
            type="file" 
            multiple 
            className="hidden" 
            ref={fileInputRef} 
            onChange={handleFileSelect}
          />
          
          <input 
            id="camera-input"
            type="file" 
            accept="image/*" 
            capture="environment"
            className="hidden" 
            onChange={handleFileSelect}
          />

          <input 
            id="photo-input"
            type="file" 
            accept="image/*" 
            multiple
            className="hidden" 
            onChange={handleFileSelect}
          />
          
          <div className="flex-1 bg-slate-50 rounded-xl border border-slate-200 focus-within:bg-white focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-100 transition-all duration-200 group overflow-hidden">
              <textarea 
                ref={textareaRef}
                value={text}
                onChange={e => setText(e.target.value)}
                onFocus={() => { setShowMenu(false); setShowTagInput(false); }}
                placeholder="Note down your memo..."
                className="w-full bg-transparent text-slate-800 placeholder-slate-400 focus:outline-none resize-none py-3 px-4 text-sm max-h-32 min-h-[44px] leading-relaxed no-scrollbar"
                rows={1}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSubmit(e);
                    }
                }}
              />
          </div>
          
          <button 
            type="submit" 
            disabled={isPending || (!text.trim() && !files.length)}
            className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-30 disabled:grayscale transition-all shadow-md active:scale-95 flex items-center justify-center"
          >
            {isPending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} className="ml-0.5" />}
          </button>
       </form>
    </div>
  )
}
