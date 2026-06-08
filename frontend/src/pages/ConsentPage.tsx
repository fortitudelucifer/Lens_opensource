import { ShieldCheck, AlertTriangle, Lock, UserCheck, CheckCircle2 } from 'lucide-react'

const SECTIONS = [
  {
    icon: AlertTriangle,
    iconColor: 'text-amber-500',
    heading: '产品定位声明',
    content:
      'Lens 是一款基于人工智能的关系模式分析与情感支持工具。\n\n' +
      '⚠️ 本工具不是医疗器械，不提供任何形式的心理诊断、治疗或处方建议。\n' +
      '⚠️ 如果您正在经历严重的心理困扰，请寻求持证心理咨询师或精神科医生的帮助。',
  },
  {
    icon: ShieldCheck,
    iconColor: 'text-blue-500',
    heading: 'AI 能力边界',
    content:
      '· AI 的分析基于有限的文本信息，无法替代面对面的专业评估\n' +
      '· AI 可能产生不准确或不恰当的回应，请以您自身判断为准\n' +
      '· 所有建议均不构成专业心理咨询意见',
  },
  {
    icon: Lock,
    iconColor: 'text-emerald-500',
    heading: '隐私保护',
    content:
      '· 您的对话内容仅保存在本地设备，不会上传到任何服务器\n' +
      '· 您可以随时删除所有对话记录\n' +
      '· 匿名化处理确保原始聊天记录中的真实身份信息不会泄露',
  },
  {
    icon: UserCheck,
    iconColor: 'text-violet-500',
    heading: '使用承诺',
    content:
      '继续使用即表示您：\n' +
      '✓ 理解本工具的非医疗定位\n' +
      '✓ 理解 AI 分析仅供参考，不替代专业服务\n' +
      '✓ 同意在遇到紧急心理危机时拨打专业热线\n' +
      '✓ 年满 18 周岁（或已获监护人同意）',
  },
]

export function ConsentPage() {
  return (
    <div className="flex-1 overflow-y-auto w-full p-6 sm:p-10" style={{ background: 'var(--bg-primary)' }}>
      <div className="max-w-4xl mx-auto space-y-8">
        
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-5 border-b pb-6" style={{ borderColor: 'var(--border-color)' }}>
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-[var(--border-color)] flex items-center justify-center shrink-0 shadow-sm">
            <ShieldCheck className="w-7 h-7 text-emerald-500 drop-shadow-sm" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>知情同意与使用须知</h1>
            <p className="text-sm mt-1.5" style={{ color: 'var(--text-muted)' }}>Lens 聆诉 — 专注于关系模式与情感支持的多模态 AI 联合分析平台</p>
          </div>
        </div>

        {/* Content Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {SECTIONS.map((s, i) => {
            const bgClass = s.iconColor.replace('text-', 'bg-').concat('/10')
            return (
              <div key={i} className="p-6 rounded-2xl border transition-shadow hover:shadow-md" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="flex items-center gap-3 mb-4">
                  <div className={`p-2.5 rounded-xl ${bgClass} border`} style={{ borderColor: 'var(--border-color)' }}>
                     <s.icon className={`w-5 h-5 ${s.iconColor}`} />
                  </div>
                  <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{s.heading}</h3>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: 'var(--text-secondary)' }}>
                  {s.content}
                </p>
              </div>
            )
          })}
        </div>

        {/* Status Box */}
        <div className="mt-8 p-6 rounded-2xl border shadow-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-start gap-4">
            <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-base font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>用户确认状态</h4>
              <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--text-secondary)' }}>
                由于本平台采用完全本地私有化部署策略，您在此设备上持续使用各项顾问服务，即等同于已阅读、理解并接受本页列出的《使用须知与知情同意》。平台不会向云端发送您的同意记录日志。
              </p>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>本地存储状态：</span>
                <code className="text-xs px-2 py-1 rounded-md font-mono border" style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
                  lens_consent_accepted = true
                </code>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
