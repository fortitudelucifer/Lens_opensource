import { useEffect, useState, useCallback } from "react"
import { useTranslation } from "react-i18next"
import {
  CheckCircle2, XCircle, Edit3, ChevronLeft, ChevronRight,
  AlertTriangle, Star, Loader2, Eye,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { api, type ReviewItemSummary, type ReviewItemDetail, type ReviewListResponse } from "@/lib/api"

type FilterType = "all" | "pending" | "passed" | "failed"

export default function ReviewPanel() {
  const { t } = useTranslation()
  const [list, setList] = useState<ReviewListResponse | null>(null)
  const [filter, setFilter] = useState<FilterType>("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ReviewItemDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [notes, setNotes] = useState("")
  const [editedAnalysis, setEditedAnalysis] = useState("")
  const [isEditing, setIsEditing] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const fetchList = useCallback(() => {
    api.getReviewItems("neutral", filter).then(setList).catch(console.error)
  }, [filter])

  useEffect(() => {
    fetchList()
    const timer = setInterval(fetchList, 10000)
    return () => clearInterval(timer)
  }, [fetchList])

  const openDetail = async (id: string) => {
    setLoading(true)
    setSelectedId(id)
    setIsEditing(false)
    setNotes("")
    try {
      const d = await api.getReviewItem(id)
      setDetail(d)
      setEditedAnalysis(JSON.stringify(d.analysis_features, null, 2))
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const submitDecision = async (decision: "approve" | "reject" | "edit") => {
    if (!selectedId) return
    setSubmitting(true)
    try {
      await api.submitReviewDecision(selectedId, {
        decision,
        notes: notes || undefined,
        edited_analysis: decision === "edit" ? editedAnalysis : undefined,
      })
      fetchList()
      // Advance to next item
      if (list) {
        const idx = list.items.findIndex((i) => i.id === selectedId)
        if (idx >= 0 && idx < list.items.length - 1) {
          openDetail(list.items[idx + 1].id)
        } else {
          setSelectedId(null)
          setDetail(null)
        }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setSubmitting(false)
    }
  }

  const stats = list?.stats

  // ── Loading view ────────────────────────────────────────────
  if (selectedId && loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // ── Detail view ────────────────────────────────────────────
  if (selectedId && detail) {
    const review = detail.review
    const scores = review?.scores || {}
    const dims = ["accuracy", "depth", "balance", "safety", "structure"]
    const dimLabels: Record<string, string> = {
      accuracy: t('reviewPanel.accuracy'), depth: t('reviewPanel.depth'), balance: t('reviewPanel.balance'),
      safety: t('reviewPanel.safety'), structure: t('reviewPanel.structure'),
    }

    return (
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Button variant="ghost" size="sm" onClick={() => { setSelectedId(null); setDetail(null) }}>
            <ChevronLeft className="w-4 h-4 mr-1" /> {t('reviewPanel.backToList')}
          </Button>
          <span className="text-sm text-muted-foreground">ID: {detail.chunk_id}</span>
          <div className="flex-1" />
          {detail.human_decision && (
            <Badge variant={detail.human_decision === "approve" ? "success" : "destructive"}>
              {detail.human_decision === "approve" ? t('reviewPanel.approved') : detail.human_decision === "reject" ? t('reviewPanel.rejected') : t('reviewPanel.edited')}
            </Badge>
          )}
        </div>

        <div className="flex-1 overflow-auto px-4 py-4 space-y-4">
          {/* AI Review Scores */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Star className="w-4 h-4 text-amber-500" />
                {t('reviewPanel.aiReviewScore')}
                <Badge variant={review?.passed ? "success" : "destructive"} className="ml-auto text-xs">
                  {review?.total_score ?? 0}/50 · {review?.passed ? t('reviewPanel.pass') : t('reviewPanel.fail')}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-5 gap-3">
                {dims.map((dim) => (
                  <div key={dim} className="text-center">
                    <div className="text-[11px] text-muted-foreground">{dimLabels[dim]}</div>
                    <div className={cn(
                      "text-lg font-bold mt-1",
                      (scores[dim] ?? 0) >= 8 ? "text-emerald-600" :
                      (scores[dim] ?? 0) >= 5 ? "text-amber-600" : "text-red-600"
                    )}>
                      {scores[dim] ?? "—"}
                    </div>
                    <div className="flex gap-0.5 justify-center mt-1">
                      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((s) => (
                        <div key={s} className={cn(
                          "w-1.5 h-1.5 rounded-full",
                          s <= (scores[dim] ?? 0) ? "bg-amber-400" : "bg-gray-200"
                        )} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {review?.summary && (
                <div className="mt-3 text-sm text-muted-foreground border-t pt-2">
                  {review.summary}
                </div>
              )}
              {review?.issues && review.issues.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">{t('reviewPanel.issuesFound')}</div>
                  {review.issues.map((issue, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs p-2 rounded bg-muted/50">
                      <AlertTriangle className={cn(
                        "w-3.5 h-3.5 shrink-0 mt-0.5",
                        issue.severity === "high" ? "text-red-500" :
                        issue.severity === "medium" ? "text-amber-500" : "text-blue-500"
                      )} />
                      <div>
                        <span className="font-medium">[{dimLabels[issue.dimension] || issue.dimension}]</span>{" "}
                        {issue.description}
                        {issue.suggestion && (
                          <div className="text-muted-foreground mt-0.5">{t('reviewPanel.suggestion', { text: issue.suggestion })}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Conversation */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('reviewPanel.originalConversation')}</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs whitespace-pre-wrap max-h-60 overflow-auto bg-muted/30 rounded p-3 font-mono">
                {detail.conversation || t('reviewPanel.noConversation')}
              </pre>
            </CardContent>
          </Card>

          {/* Analysis */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                {t('reviewPanel.llmAnalysis')}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto h-6 text-xs"
                  onClick={() => setIsEditing(!isEditing)}
                >
                  <Edit3 className="w-3 h-3 mr-1" />
                  {isEditing ? t('reviewPanel.preview') : t('reviewPanel.edit')}
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isEditing ? (
                <Textarea
                  className="font-mono text-xs min-h-[200px]"
                  value={editedAnalysis}
                  onChange={(e) => setEditedAnalysis(e.target.value)}
                />
              ) : (
                <pre className="text-xs whitespace-pre-wrap max-h-80 overflow-auto bg-muted/30 rounded p-3 font-mono">
                  {editedAnalysis}
                </pre>
              )}
            </CardContent>
          </Card>

          {/* Notes */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t('reviewPanel.reviewNotes')}</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                placeholder={t('reviewPanel.notesPlaceholder')}
                className="text-sm min-h-[60px]"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </CardContent>
          </Card>
        </div>

        {/* Action bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-t border-border bg-muted/20">
          <Button
            className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white"
            disabled={submitting}
            onClick={() => submitDecision("approve")}
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
            {t('reviewPanel.approve')}
          </Button>
          <Button
            variant="outline"
            className="flex-1 border-amber-300 text-amber-700 hover:bg-amber-50"
            disabled={submitting}
            onClick={() => submitDecision("edit")}
          >
            <Edit3 className="w-4 h-4 mr-1" />
            {t('reviewPanel.saveEdit')}
          </Button>
          <Button
            variant="destructive"
            className="flex-1"
            disabled={submitting}
            onClick={() => submitDecision("reject")}
          >
            <XCircle className="w-4 h-4 mr-1" />
            {t('reviewPanel.reject')}
          </Button>
        </div>
      </div>
    )
  }

  // ── List view ──────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* Header + stats */}
      <div className="px-4 py-3 border-b border-border space-y-3">
        <h2 className="text-base font-semibold">{t('reviewPanel.title')}</h2>
        {stats && (
          <div className="flex gap-3 text-xs">
            <span className="px-2 py-1 rounded bg-muted">{t('reviewPanel.total', { count: stats.total })}</span>
            <span className="px-2 py-1 rounded bg-emerald-50 text-emerald-700">{t('reviewPanel.aiPassed', { count: stats.ai_passed })}</span>
            <span className="px-2 py-1 rounded bg-red-50 text-red-700">{t('reviewPanel.aiFailed', { count: stats.ai_failed })}</span>
            <span className="px-2 py-1 rounded bg-blue-50 text-blue-700">{t('reviewPanel.humanApproved', { count: stats.human_approved })}</span>
            <span className="px-2 py-1 rounded bg-amber-50 text-amber-700">{t('reviewPanel.pending', { count: stats.pending })}</span>
          </div>
        )}
        <div className="flex gap-1">
          {(["all", "pending", "passed", "failed"] as FilterType[]).map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "ghost"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setFilter(f)}
            >
              {{ all: t('reviewPanel.filterAll'), pending: t('reviewPanel.filterPending'), passed: t('reviewPanel.filterPassed'), failed: t('reviewPanel.filterFailed') }[f]}
            </Button>
          ))}
        </div>
      </div>

      {/* Items */}
      <div className="flex-1 overflow-auto">
        {!list || list.items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm">
            <Eye className="w-8 h-8 mb-2 opacity-40" />
            {!list ? t('reviewPanel.loading') : t('reviewPanel.noItems')}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {list.items.map((item) => (
              <ReviewItemRow
                key={item.id}
                item={item}
                onClick={() => openDetail(item.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ReviewItemRow({ item, onClick }: { item: ReviewItemSummary; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <div
      className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 cursor-pointer transition-colors"
      onClick={onClick}
    >
      {/* Score circle */}
      <div className={cn(
        "w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0",
        item.ai_score >= 36 ? "bg-emerald-100 text-emerald-700" :
        item.ai_score >= 24 ? "bg-amber-100 text-amber-700" :
        "bg-red-100 text-red-700"
      )}>
        {item.ai_score}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{item.chunk_id || "—"}</span>
          <Badge variant={item.ai_passed ? "success" : "destructive"} className="text-[10px]">
            {t('reviewPanel.aiLabel', { status: item.ai_passed ? t('reviewPanel.pass') : t('reviewPanel.fail') })}
          </Badge>
          {item.human_decision && (
            <Badge
              variant={item.human_decision === "approve" ? "success" : item.human_decision === "reject" ? "destructive" : "secondary"}
              className="text-[10px]"
            >
              {t('reviewPanel.humanLabel', { status: item.human_decision === "approve" ? t('reviewPanel.approved') : item.human_decision === "reject" ? t('reviewPanel.rejected') : t('reviewPanel.edited') })}
            </Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground mt-0.5 truncate">
          {item.ai_summary || item.conversation_preview || "—"}
        </div>
      </div>

      <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
    </div>
  )
}
