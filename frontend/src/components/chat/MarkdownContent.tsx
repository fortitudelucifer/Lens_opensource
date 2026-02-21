import type { ReactNode } from 'react'

interface MarkdownContentProps {
  content: string
  isUser?: boolean
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const result: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
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
  const lines = content.split('\n')
  const blocks: ReactNode[] = []

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]

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

    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items: string[] = [line.slice(2)]
      while (i + 1 < lines.length && (lines[i + 1].startsWith('- ') || lines[i + 1].startsWith('* '))) {
        i += 1
        items.push(lines[i].slice(2))
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
