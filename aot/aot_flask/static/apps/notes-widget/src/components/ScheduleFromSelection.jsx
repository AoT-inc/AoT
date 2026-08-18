import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, X } from 'lucide-react'
import { t } from '../lib/i18n'
import { linkSelectionToSchedule } from '../lib/api'

// 선택한 구간을 예정으로 — **분기는 쓴 뒤에 온다.**
//
// 예전에는 쓰기 전에 "노트인가 일정인가" 를 고르게 했다. 그 구분은 저장
// 테이블 이름이지 사람이 아는 구분이 아니고, 실제로 경계는 양방향으로 새고
// 있었다(`action_type='note'` 인 일정과 `category='schedule'` 인 노트가 둘 다
// 있다). 이제 사용자는 노트만 쓰고, 쓴 뒤에 한 구간을 골라 시각을 준다.
//
// **내용을 다시 묻지 않는다** — 고른 텍스트가 곧 내용이다. 여기서 입력을 또
// 받기 시작하면 노트와 예정이 다시 서로 다른 글이 된다.

// 기본값은 오늘 + 다음 정시. 사람이 이미 "예정으로" 를 눌러 뜻을 밝힌 뒤라
// 기본값이 선택을 대신하지 않는다(폼 안에서 갈리던 옛 방식과 다른 점).
// 다음 정시로 두는 이유는 지나간 시각이 기본으로 들어가면 안 되기 때문이다.
function defaultWhen() {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  const p = (n) => String(n).padStart(2, '0')
  return {
    date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
    time: `${p(d.getHours())}:00`,
  }
}

export default function ScheduleFromSelection({ selection, targetId, onDone, barRef }) {
  const [open, setOpen] = useState(false)
  const [when, setWhen] = useState(defaultWhen)
  const [worker, setWorker] = useState('')
  const [err, setErr] = useState('')
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: () => linkSelectionToSchedule(selection.noteId, {
      start: selection.start, end: selection.end, text: selection.text,
      date: when.date, time: when.time, worker,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes', targetId] })
      setOpen(false); setWorker(''); setErr(''); setWhen(defaultWhen())
      onDone && onDone()
    },
    onError: (e) => {
      const d = e && e.response && e.response.data
      setErr((d && d.message) || t('Save failed'))
    },
  })

  const preview = selection.text.length > 40
    ? selection.text.slice(0, 40) + '…' : selection.text

  return (
    <div ref={barRef} className="mt-auto sticky bottom-0 z-20 -mx-4 px-4 pb-2 pt-2 bg-white/95 backdrop-blur border-t border-slate-200">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 text-white text-sm font-medium"
        >
          <CalendarPlus size={16} />
          <span className="truncate">{t('Schedule this')}</span>
          <span className="ml-auto truncate opacity-60 text-xs">{preview}</span>
        </button>
      ) : (
        <div className="rounded-lg border border-slate-200 p-3 space-y-2">
          <div className="flex items-start gap-2">
            <div className="text-xs text-slate-500 flex-1 break-words">{selection.text}</div>
            <button type="button" onClick={() => { setOpen(false); setErr('') }}
                    className="text-slate-400 shrink-0"><X size={16} /></button>
          </div>
          <div className="flex gap-2">
            <input type="date" value={when.date} className="flex-1 border rounded px-2 py-1 text-sm"
                   onChange={(e) => setWhen({ ...when, date: e.target.value })} />
            <input type="time" value={when.time} className="w-28 border rounded px-2 py-1 text-sm"
                   onChange={(e) => setWhen({ ...when, time: e.target.value })} />
          </div>
          <input type="text" value={worker} placeholder={t('Worker')}
                 className="w-full border rounded px-2 py-1 text-sm"
                 onChange={(e) => setWorker(e.target.value)} />
          {err && <div className="text-xs text-red-500">{err}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setOpen(false); setErr('') }}
                    className="px-3 py-1 text-sm text-slate-600">{t('Cancel')}</button>
            <button type="button" disabled={save.isPending || !when.date}
                    onClick={() => save.mutate()}
                    className="px-3 py-1 text-sm rounded bg-slate-900 text-white disabled:opacity-40">
              {t('Save')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
