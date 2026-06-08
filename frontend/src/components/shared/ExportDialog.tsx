import { useState } from 'react'
import { Download, X, FileJson, FileText } from 'lucide-react'

type ExportFormat = 'json' | 'markdown'

interface ExportDialogProps {
  open: boolean
  onClose: () => void
  title?: string
  getData: () => { json: unknown; markdown: string; filename: string }
}

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function ExportDialog({ open, onClose, title = '导出对话', getData }: ExportDialogProps) {
  const [fmt, setFmt] = useState<ExportFormat>('markdown')

  if (!open) return null

  const handleExport = () => {
    const { json, markdown, filename } = getData()
    if (fmt === 'json') {
      downloadFile(JSON.stringify(json, null, 2), `${filename}.json`, 'application/json')
    } else {
      downloadFile(markdown, `${filename}.md`, 'text/markdown')
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-sm mx-4 rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-[var(--text-primary)]">{title}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-[var(--bg-secondary)] text-[var(--text-muted)]">
            <X size={16} />
          </button>
        </div>
        <div className="flex gap-3">
          <button onClick={() => setFmt('markdown')}
            className={`flex-1 flex flex-col items-center gap-2 p-4 rounded-xl border transition-colors ${fmt === 'markdown' ? 'border-emerald-500 bg-emerald-500/10' : 'border-[var(--border-color)] hover:bg-[var(--bg-secondary)]'}`}>
            <FileText className={`w-6 h-6 ${fmt === 'markdown' ? 'text-emerald-500' : 'text-[var(--text-muted)]'}`} />
            <span className="text-xs font-medium text-[var(--text-primary)]">Markdown</span>
            <span className="text-[10px] text-[var(--text-muted)]">可读性强</span>
          </button>
          <button onClick={() => setFmt('json')}
            className={`flex-1 flex flex-col items-center gap-2 p-4 rounded-xl border transition-colors ${fmt === 'json' ? 'border-emerald-500 bg-emerald-500/10' : 'border-[var(--border-color)] hover:bg-[var(--bg-secondary)]'}`}>
            <FileJson className={`w-6 h-6 ${fmt === 'json' ? 'text-emerald-500' : 'text-[var(--text-muted)]'}`} />
            <span className="text-xs font-medium text-[var(--text-primary)]">JSON</span>
            <span className="text-[10px] text-[var(--text-muted)]">完整数据</span>
          </button>
        </div>
        <button onClick={handleExport}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 transition-colors">
          <Download className="w-4 h-4" /> 导出
        </button>
      </div>
    </div>
  )
}

/** 将沉浸式互动的 messages 转为导出数据 */
export function chatToExportData(messages: Array<{ role: string; content: string; timestamp?: Date | string }>, sessionTitle?: string) {
  const ts = new Date().toISOString().slice(0, 10)
  const filename = `chat_${sessionTitle?.slice(0, 15) || ts}`

  const md = messages.map(m => {
    const role = m.role === 'user' ? '**用户**' : '**顾问**'
    return `${role}\n\n${m.content}`
  }).join('\n\n---\n\n')

  return {
    json: { title: sessionTitle, exported_at: new Date().toISOString(), messages },
    markdown: `# ${sessionTitle || '对话记录'}\n\n导出时间：${new Date().toLocaleString('zh-CN')}\n\n---\n\n${md}`,
    filename,
  }
}

/** 将 Arena 对比的 rounds 转为导出数据 */
export function arenaToExportData(
  rounds: Array<{ query: string; responseA: string; responseB: string; vote?: string | null; timestamp?: Date | string }>,
  contestantA?: Record<string, string> | null,
  contestantB?: Record<string, string> | null,
  sessionTitle?: string,
) {
  const ts = new Date().toISOString().slice(0, 10)
  const filename = `arena_${sessionTitle?.slice(0, 15) || ts}`
  const lblA = contestantA?.model || contestantA?.backend || 'A'
  const lblB = contestantB?.model || contestantB?.backend || 'B'

  const md = rounds.map((rd, i) => {
    const voteStr = rd.vote ? `\n\n> 投票结果：${rd.vote}` : ''
    return `## 第 ${i + 1} 轮\n\n**用户**\n\n${rd.query}\n\n**回复 A**（${lblA}）\n\n${rd.responseA}\n\n**回复 B**（${lblB}）\n\n${rd.responseB}${voteStr}`
  }).join('\n\n---\n\n')

  return {
    json: {
      title: sessionTitle,
      exported_at: new Date().toISOString(),
      contestant_a: contestantA,
      contestant_b: contestantB,
      rounds,
    },
    markdown: `# 双镜对比：${sessionTitle || '对话记录'}\n\nA = ${lblA} | B = ${lblB}\n\n导出时间：${new Date().toLocaleString('zh-CN')}\n\n---\n\n${md}`,
    filename,
  }
}
