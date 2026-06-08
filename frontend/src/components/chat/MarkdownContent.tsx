import type { ReactNode } from 'react'

interface MarkdownContentProps {
  content: string
  isUser?: boolean
}

const MD_LINE_RE = /^(\s*[-*+]\s|#{1,6}\s|\d+\.\s|>\s|```|\|)/

function normalizeMarkdownContent(raw: string): string {
  const normalized = raw
    .replace(/\r\n?/g, '\n')
    .replace(/[\u00A0\u3000]/g, ' ')
    .replace(/\t/g, '    ')

  const lines = normalized.split('\n').map((line) => line.replace(/\s+$/g, ''))
  const rebuilt: string[] = []

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li]
    const prev = rebuilt.length > 0 ? rebuilt[rebuilt.length - 1] : ''

    if (
      li > 0 && prev.trim() && line.trim() &&
      !MD_LINE_RE.test(line) && !MD_LINE_RE.test(prev) &&
      !/[。！？：；.!?:;]$/.test(prev) && !/\s{2}$/.test(prev)
    ) {
      rebuilt[rebuilt.length - 1] += line
      continue
    }

    const splitLine = line
      .replace(/\s{3,}(?=(?:>\s*|[*+-]\s+|\d+\.\s+))/g, '\n')
      .replace(/^(\s*>\s*)\*\s*"?/g, '$1* "')
    rebuilt.push(...splitLine.split('\n'))
  }

  return rebuilt.join('\n')
}

function parseTableRow(line: string): string[] {
  const trimmed = line.trim()
  const withoutOuterPipes = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  return withoutOuterPipes.split('|').map((cell) => cell.trim())
}

function isTableSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line)
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const result: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  let part = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      result.push(text.slice(lastIndex, match.index))
    }

    const token = match[0]
    const key = `${keyPrefix}-${part++}`

    if (token.startsWith('**') && token.endsWith('**')) {
      result.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*') && token.endsWith('*')) {
      result.push(<em key={key}>{token.slice(1, -1)}</em>)
    } else if (token.startsWith('`') && token.endsWith('`')) {
      result.push(
        <code key={key} className="rounded bg-black/10 px-1 py-0.5 text-[0.92em] dark:bg-white/10">
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      if (linkMatch) {
        result.push(
          <a
            key={key}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2"
          >
            {linkMatch[1]}
          </a>,
        )
      } else {
        result.push(token)
      }
    }

    lastIndex = pattern.lastIndex
  }

  if (lastIndex < text.length) {
    result.push(text.slice(lastIndex))
  }

  return result
}

export function MarkdownContent({ content, isUser = false }: MarkdownContentProps) {
  const lines = normalizeMarkdownContent(content).split('\n')
  const blocks: ReactNode[] = []

  const nextNonEmptyLineIndex = (from: number) => {
    let idx = from
    while (idx < lines.length && !lines[idx].trim()) {
      idx += 1
    }
    return idx
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    const trimmedStart = line.trimStart()

    if (!line.trim()) {
      blocks.push(<div key={`gap-${i}`} className="h-2" />)
      continue
    }

    if (line.startsWith('```')) {
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i += 1
      }
      blocks.push(
        <pre
          key={`code-${i}`}
          className="overflow-x-auto rounded-xl border border-black/10 bg-black/10 p-3 text-xs leading-relaxed dark:border-white/10 dark:bg-white/10"
        >
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      continue
    }

    if (/^\d+\.\s+/.test(trimmedStart)) {
      const items: string[] = [trimmedStart.replace(/^\d+\.\s+/, '')]
      while (i + 1 < lines.length && /^\d+\.\s+/.test(lines[i + 1].trimStart())) {
        i += 1
        items.push(lines[i].trimStart().replace(/^\d+\.\s+/, ''))
      }
      blocks.push(
        <ol key={`olist-${i}`} className="list-decimal space-y-1 pl-5">
          {items.map((item, idx) => (
            <li key={`olist-item-${i}-${idx}`}>{renderInline(item, `olist-${i}-${idx}`)}</li>
          ))}
        </ol>,
      )
      continue
    }

    const quoteMatch = line.match(/^\s*>\s?(.*)$/)
    if (quoteMatch) {
      const quoteLines: string[] = [quoteMatch[1]]
      while (i + 1 < lines.length) {
        const nextQuote = lines[i + 1].match(/^\s*>\s?(.*)$/)
        if (!nextQuote) break
        i += 1
        quoteLines.push(nextQuote[1])
      }
      blocks.push(
        <blockquote
          key={`quote-${i}`}
          className="rounded-lg border-l-4 border-emerald-500/50 bg-emerald-500/5 px-3 py-2 text-[var(--text-secondary)]"
        >
          {quoteLines.map((quoteLine, idx) => (
            <p key={`quote-line-${i}-${idx}`} className="whitespace-pre-wrap leading-relaxed">
              {renderInline(quoteLine, `quote-${i}-${idx}`)}
            </p>
          ))}
        </blockquote>,
      )
      continue
    }

    if (/^[-*+]\s+/.test(trimmedStart)) {
      const items: string[] = [trimmedStart.replace(/^[-*+]\s+/, '')]
      while (i + 1 < lines.length && /^[-*+]\s+/.test(lines[i + 1].trimStart())) {
        i += 1
        items.push(lines[i].trimStart().replace(/^[-*+]\s+/, ''))
      }
      blocks.push(
        <ul key={`list-${i}`} className="list-disc space-y-1 pl-5">
          {items.map((item, idx) => (
            <li key={`item-${i}-${idx}`}>{renderInline(item, `list-${i}-${idx}`)}</li>
          ))}
        </ul>,
      )
      continue
    }

    const separatorIdx = nextNonEmptyLineIndex(i + 1)
    if (line.includes('|') && separatorIdx < lines.length && isTableSeparator(lines[separatorIdx])) {
      const headerCells = parseTableRow(line)
      const rows: string[][] = []
      i = separatorIdx + 1

      while (i < lines.length) {
        if (!lines[i].trim()) {
          const peek = nextNonEmptyLineIndex(i + 1)
          if (peek < lines.length && lines[peek].includes('|')) {
            i = peek
          } else {
            break
          }
        }
        if (!lines[i].includes('|')) {
          break
        }
        rows.push(parseTableRow(lines[i]))
        i += 1
      }

      i -= 1

      blocks.push(
        <div key={`table-${i}`} className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/10">
          <table className="min-w-full text-sm">
            <thead className="bg-black/5 dark:bg-white/5">
              <tr>
                {headerCells.map((cell, idx) => (
                  <th key={`th-${i}-${idx}`} className="border-b border-black/10 px-3 py-2 text-left font-semibold dark:border-white/10">
                    {renderInline(cell, `th-${i}-${idx}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr key={`tr-${i}-${rowIdx}`} className="border-b last:border-b-0 border-black/10 dark:border-white/10">
                  {headerCells.map((_, colIdx) => (
                    <td key={`td-${i}-${rowIdx}-${colIdx}`} className="px-3 py-2 align-top">
                      {renderInline(row[colIdx] || '', `td-${i}-${rowIdx}-${colIdx}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    const heading = line.match(/^(#{1,6})\s*(.+)$/)
    if (heading) {
      const depth = heading[1].length
      const title = heading[2].trim()
      if (!title) {
        continue
      }
      const cls =
        depth === 1
          ? 'text-lg font-bold'
          : depth === 2
            ? 'text-base font-semibold'
            : depth === 3
              ? 'text-sm font-semibold'
              : 'text-sm font-medium'
      blocks.push(
        <p key={`heading-${i}`} className={cls}>
          {renderInline(title, `heading-${i}`)}
        </p>
      )
      continue
    }

    blocks.push(
      <p key={`p-${i}`} className="whitespace-pre-wrap leading-relaxed">
        {renderInline(line, `p-${i}`)}
      </p>,
    )
  }

  return (
    <div className={`space-y-1 ${isUser ? 'text-white/95' : 'text-[var(--text-primary)]'}`}>
      {blocks}
    </div>
  )
}
