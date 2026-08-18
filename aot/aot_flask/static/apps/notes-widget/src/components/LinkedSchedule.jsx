import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, AlertTriangle } from 'lucide-react'
import { t } from '../lib/i18n'
import { unlinkSchedule } from '../lib/api'

// 이 노트에 걸린 예정들.
//
// **고아(본문에서 사라진 구간)를 숨기지 않는다.** 숨기면 아무도 취소하지
// 못하는 약속이 남는다. 반대로 본문이 지워졌다는 이유로 자동 취소하면, 오타
// 하나 고치다 잡아둔 약속이 사라진다. 그래서 화면에 드러내 놓고 **사람이
// 정하게** 한다 — 링크만 끊을지, 예정까지 취소할지.

function whenText(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return String(iso)
  const p = (n) => String(n).padStart(2, '0')
  const now = new Date()
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  if (d.toDateString() === now.toDateString()) return hm
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

export default function LinkedSchedule({ links, targetId }) {
  const [openId, setOpenId] = useState(null)
  const qc = useQueryClient()

  const drop = useMutation({
    mutationFn: ({ linkId, cancelJob }) => unlinkSchedule(linkId, cancelJob),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes', targetId] })
      setOpenId(null)
    },
  })

  const rows = links || []
  if (!rows.length) return null

  return (
    <div className="space-y-1">
      {rows.map((l) => {
        const open = openId === l.link_id
        return (
          <div key={l.link_id} className="rounded-lg border border-slate-200 overflow-hidden">
            <button
              type="button"
              onClick={() => setOpenId(open ? null : l.link_id)}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left"
            >
              {l.orphaned
                ? <AlertTriangle size={14} className="text-amber-500 shrink-0" />
                : <CalendarClock size={14} className="text-slate-400 shrink-0" />}
              <span className="text-xs text-slate-700 truncate flex-1">{l.text}</span>
              <span className="text-[11px] text-slate-500 shrink-0">{whenText(l.when)}</span>
            </button>

            {l.orphaned && (
              <div className="px-2.5 pb-1.5 text-[11px] text-amber-600">
                {t('This text is no longer in the note')}
              </div>
            )}

            {open && (
              <div className="px-2.5 pb-2 flex justify-end gap-2">
                {/* 기본은 예정을 남기는 것 — 이미 잡힌 약속이 글 편집으로
                    조용히 사라지면 안 된다. */}
                <button type="button" disabled={drop.isPending}
                        onClick={() => drop.mutate({ linkId: l.link_id, cancelJob: false })}
                        className="px-2 py-1 text-[11px] text-slate-600 disabled:opacity-40">
                  {t('Unlink only')}
                </button>
                <button type="button" disabled={drop.isPending}
                        onClick={() => drop.mutate({ linkId: l.link_id, cancelJob: true })}
                        className="px-2 py-1 text-[11px] rounded bg-red-50 text-red-600 disabled:opacity-40">
                  {t('Cancel the schedule')}
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
