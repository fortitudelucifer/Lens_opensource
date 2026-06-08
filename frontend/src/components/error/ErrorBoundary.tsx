import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw, Copy, ChevronDown } from 'lucide-react'

interface Props {
  children: ReactNode
  /** 自定义降级 UI，未指定时使用内置 fallback */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
  detailsOpen: boolean
}

/**
 * 全局 Error Boundary —— React 生命周期错误 → 降级 UI，避免白屏。
 *
 * 捕获范围：
 *   - 渲染阶段抛出的错误
 *   - 生命周期方法错误
 *   - 子组件构造函数错误
 *
 * **不捕获**：事件处理函数、异步回调、SSR（这些需要 try/catch + toast.error）。
 *
 * 使用：
 *   <ErrorBoundary><App /></ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, errorInfo: null, detailsOpen: false }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 输出到控制台便于开发者调试
    console.error('[ErrorBoundary] Caught an error:', error)
    console.error('[ErrorBoundary] Component stack:', errorInfo.componentStack)
    this.setState({ errorInfo })
    // TODO: 可选——自动上报到 /api/feedback 作为 Bug 记录
  }

  reset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null, detailsOpen: false })
  }

  handleReload = () => {
    window.location.reload()
  }

  handleCopy = () => {
    if (!this.state.error) return
    const text = [
      `Error: ${this.state.error.message}`,
      `Stack: ${this.state.error.stack || '(no stack)'}`,
      `Component Stack: ${this.state.errorInfo?.componentStack || '(no component stack)'}`,
      `URL: ${window.location.href}`,
      `UA: ${navigator.userAgent}`,
      `Time: ${new Date().toISOString()}`,
    ].join('\n\n')
    navigator.clipboard?.writeText(text).catch(() => {})
  }

  render() {
    if (!this.state.hasError || !this.state.error) {
      return this.props.children
    }

    if (this.props.fallback) {
      return this.props.fallback(this.state.error, this.reset)
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[var(--bg-primary)] text-[var(--text-primary)]">
        <div className="max-w-xl w-full rounded-2xl border border-red-500/30 bg-[var(--bg-card)] shadow-xl overflow-hidden">
          <div className="px-6 py-5 border-b border-[var(--border-color)] bg-red-500/5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-red-500/15 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-red-500" />
            </div>
            <div>
              <h2 className="text-base font-semibold">页面渲染出错</h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">应用捕获到未处理的异常，已切换到安全视图。</p>
            </div>
          </div>

          <div className="p-6 space-y-4">
            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] font-mono text-xs break-all text-red-500">
              {this.state.error.message || '(无错误消息)'}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={this.handleReload}
                className="flex items-center gap-1.5 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-lg transition-colors shadow-sm"
              >
                <RefreshCw className="w-3.5 h-3.5" /> 刷新页面
              </button>
              <button
                onClick={this.reset}
                className="px-4 py-2 bg-[var(--bg-secondary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] text-[var(--text-primary)] text-xs font-medium rounded-lg transition-colors"
              >
                返回当前页
              </button>
              <button
                onClick={this.handleCopy}
                className="ml-auto flex items-center gap-1.5 px-3 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs transition-colors"
                title="复制错误详情"
              >
                <Copy className="w-3.5 h-3.5" /> 复制详情
              </button>
            </div>

            <button
              onClick={() => this.setState((s) => ({ detailsOpen: !s.detailsOpen }))}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] border-t border-[var(--border-color)] pt-3 mt-2"
            >
              <span>开发者详情（堆栈 + 组件链）</span>
              <ChevronDown className={`w-3.5 h-3.5 transition-transform ${this.state.detailsOpen ? 'rotate-180' : ''}`} />
            </button>

            {this.state.detailsOpen && (
              <pre className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[10px] text-[var(--text-muted)] font-mono overflow-auto max-h-64 scrollbar-thin whitespace-pre-wrap break-all">
                {this.state.error.stack || '(no stack)'}
                {this.state.errorInfo?.componentStack ? `\n\n--- Component Stack ---\n${this.state.errorInfo.componentStack}` : ''}
              </pre>
            )}

            <p className="text-[11px] text-[var(--text-muted)] pt-1">
              若问题持续，请通过右下角「问题反馈」按钮或在「设置 → 问题与建议反馈」中留言，我们会跟进处理。
            </p>
          </div>
        </div>
      </div>
    )
  }
}
