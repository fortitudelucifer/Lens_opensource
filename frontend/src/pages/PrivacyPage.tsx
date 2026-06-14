import { useTranslation } from 'react-i18next'
import { ShieldCheck, Lock, Server, Trash2, Sparkles, ArrowLeft } from 'lucide-react'

interface PrivacyPageProps {
  onBack?: () => void
}

/**
 * 独立隐私政策页面（/privacy）
 *
 * 来源：`综合执行计划_v2.md` S2.2 要求的 "隐私政策页面" 独立路由。
 * 内容分层：数据生命周期 / 数据存储位置 / 透明度声明 / 用户权利 / 联系方式。
 *
 * 与设置页「隐私策略」section 的差异：
 *   - 设置页为简版摘要（嵌入在运维配置上下文中）
 *   - 本页为完整版，可直接分享 URL，对接合规审查
 */
export function PrivacyPage({ onBack }: PrivacyPageProps) {
  const { t } = useTranslation()
  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        {onBack && (
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> {t('privacy.backToSettings')}
          </button>
        )}

        {/* Header */}
        <div className="relative rounded-2xl overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/10 to-teal-500/10" />
          <div className="relative p-8">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
                <ShieldCheck className="w-5 h-5 text-emerald-500" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight">{t('privacy.title')}</h1>
            </div>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-2xl">
              Lens 聆诉（下称"本系统"）是心理健康领域的研究性质 AI 咨询助手。我们将您的隐私视为产品底线，本页详细说明数据流向、存储方式与您的权利。
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-2">最后更新：2026-04-18</p>
          </div>
        </div>

        {/* §1 非诊断声明 */}
        <Section icon={<Sparkles className="w-4 h-4 text-amber-500" />} title="使用性质声明（重要）" accent="amber">
          <ul className="list-disc pl-5 space-y-1">
            <li>本系统为<strong>研究性质 AI 咨询助手</strong>，不构成医疗诊断、心理治疗或处方建议。</li>
            <li>AI 输出仅供自我探索参考，不能替代执业心理咨询师 / 精神科医师的专业评估。</li>
            <li>若您正经历<strong>自杀/自伤意念</strong>，请立即拨打 <code className="bg-red-500/10 text-red-500 px-1.5 py-0.5 rounded text-xs">400-161-9995</code>（全国 24 小时心理援助热线），或使用侧边栏「紧急求助」按钮。</li>
          </ul>
        </Section>

        {/* §2 数据生命周期 */}
        <Section icon={<Server className="w-4 h-4 text-emerald-500" />} title="数据生命周期" accent="emerald">
          <h3 className="font-semibold text-sm mt-1">2.1 收集</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>您主动输入的对话内容</strong>：沉浸式互动 / 双镜对比 / 交流测评答案。</li>
            <li><strong>评分反馈</strong>：Arena 打分、测评结果、UI 问题反馈。</li>
            <li><strong>浏览器元数据</strong>：User Agent、当前路径（仅用于反馈 Bug 定位）。</li>
            <li><strong>不收集</strong>：Cookie 跟踪、第三方分析、广告标识、设备指纹。</li>
          </ul>

          <h3 className="font-semibold text-sm mt-3">2.2 处理</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>本地处理</strong>：Phase 6 个性化模型训练在您的本地机器执行，真实姓名/L1 数据不离开本机。</li>
            <li><strong>云端处理</strong>：Phase 2 深度分析仅使用 L2（匿名化）数据，第三方模型（DeepSeek/Claude/GPT 等）仅看到 <code>ME</code> / <code>OTHER</code> 占位符，不见真实身份。</li>
            <li><strong>SafetyLayer P0</strong>：云端返回的 rationale_private 字段不注入本地上下文。</li>
          </ul>

          <h3 className="font-semibold text-sm mt-3">2.3 存储</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>所有用户数据存储在部署本机的 <code className="bg-[var(--bg-secondary)] px-1.5 rounded text-xs">advisor_out/</code> 目录下，不上传至任何第三方服务器。</li>
            <li>浏览器 <code>localStorage</code> 仅保存主题偏好与上次选择的模型，不含对话内容。</li>
          </ul>

          <h3 className="font-semibold text-sm mt-3">2.4 删除</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>您可随时通过「设置 → 数据清除」一键删除<strong>所有</strong>对话、测评、反馈、危机归档数据。</li>
            <li>删除动作不可恢复，请事先使用「对话导出」功能自行备份重要会话。</li>
          </ul>
        </Section>

        {/* §3 AI 透明度 */}
        <Section icon={<Lock className="w-4 h-4 text-blue-500" />} title="AI 透明度声明" accent="blue">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>可解释性</strong>：双镜对比模式下，您可比较不同模型/流派对同一问题的回答差异，理解 AI 输出的多样性。</li>
            <li><strong>安全监督</strong>：所有输出经过四级危机检测 + 用词红线后处理（禁用"诊断/治疗/处方"等医学越界词）。</li>
            <li><strong>测评说明</strong>：PHQ-2/GAD-2/依恋/冲突量表仅作筛查参考，结果附解读说明，不作诊断。</li>
            <li><strong>模型身份</strong>：Arena 默认投票后揭示模型真实身份，用户可选择始终显示。</li>
          </ul>
        </Section>

        {/* §4 用户权利 */}
        <Section icon={<Trash2 className="w-4 h-4 text-red-500" />} title="您的权利" accent="red">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>访问权</strong>：所有数据以明文 JSON/JSONL 存储在 <code className="bg-[var(--bg-secondary)] px-1.5 rounded text-xs">advisor_out/</code>，可直接查阅。</li>
            <li><strong>导出权</strong>：使用对话导出功能（JSON/Markdown）下载您的会话。</li>
            <li><strong>删除权</strong>：「设置 → 数据清除」一键删除所有本地数据。</li>
            <li><strong>反馈权</strong>：通过右下角「问题反馈」按钮或「设置 → 问题与建议反馈」反馈隐私问题，我们将及时跟进。</li>
          </ul>
        </Section>

        <div className="text-center py-6 text-xs text-[var(--text-muted)]">
          <p>Lens 聆诉 · 研究性质心理健康 AI 助手</p>
          <p className="mt-1">隐私问题联系：通过「问题与建议反馈」栏目留言</p>
        </div>
      </div>
    </div>
  )
}

interface SectionProps {
  icon: React.ReactNode
  title: string
  accent: 'emerald' | 'blue' | 'amber' | 'red' | 'purple'
  children: React.ReactNode
}

function Section({ icon, title, accent, children }: SectionProps) {
  const accentMap: Record<SectionProps['accent'], string> = {
    emerald: 'bg-emerald-500',
    blue: 'bg-blue-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
    purple: 'bg-purple-500',
  }
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <div className={`w-1 h-6 ${accentMap[accent]} rounded-full`} />
        <h2 className="text-lg font-semibold flex items-center gap-2">
          {icon}
          {title}
        </h2>
      </div>
      <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 shadow-sm text-sm text-[var(--text-secondary)] leading-relaxed space-y-2">
        {children}
      </div>
    </section>
  )
}
