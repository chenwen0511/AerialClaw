/**
 * DoctorPanel.jsx — 系统健康检查面板
 */
import { useState } from 'react'

const CATEGORY_LABELS = {
  connection: '连接',
  sensor:     '传感器',
  ai:         'AI 模型',
  config:     '配置',
}

const CATEGORY_ICONS = {
  connection: '🔗',
  sensor:     '📡',
  ai:         '🤖',
  config:     '⚙️',
}

const S = {
  panel: {
    display: 'flex', flexDirection: 'column', gap: 12,
    height: '100%', overflow: 'hidden',
    color: '#e2e8f0', fontSize: 13,
    padding: 16,
  },
  card: {
    background: 'rgba(15,23,42,.7)',
    border: '1px solid rgba(0,212,255,.15)',
    borderRadius: 8,
    padding: 14,
  },
  btnRun: {
    background: 'linear-gradient(135deg,rgba(0,212,255,.25),rgba(0,212,255,.1))',
    border: '1px solid rgba(0,212,255,.5)',
    borderRadius: 8,
    color: '#00d4ff', fontSize: 14, fontWeight: 700,
    padding: '10px 28px', cursor: 'pointer',
  },
  sectionTitle: {
    fontSize: 11, fontWeight: 700, color: '#00d4ff',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 10,
  },
  checkRow: (status) => ({
    display: 'flex', alignItems: 'flex-start', gap: 10,
    padding: '9px 12px',
    background: status === 'ok'   ? 'rgba(34,197,94,.06)'
              : status === 'warn' ? 'rgba(245,158,11,.06)'
              :                     'rgba(239,68,68,.06)',
    border: `1px solid ${
      status === 'ok'   ? 'rgba(34,197,94,.2)'
    : status === 'warn' ? 'rgba(245,158,11,.2)'
    :                     'rgba(239,68,68,.2)'
    }`,
    borderRadius: 7,
    marginBottom: 6,
  }),
}

function statusIcon(s) {
  if (s === 'ok')   return { icon: '✅', color: '#4ade80' }
  if (s === 'warn') return { icon: '⚠️', color: '#fbbf24' }
  return               { icon: '❌', color: '#f87171' }
}

function scoreColor(score) {
  if (score >= 80) return '#4ade80'
  if (score >= 50) return '#fbbf24'
  return '#f87171'
}

export default function DoctorPanel() {
  const [running,  setRunning]  = useState(false)
  const [result,   setResult]   = useState(null) // { score, checks: [] }
  const [error,    setError]    = useState(null)

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    try {
      const res  = await fetch('/api/doctor/run')
      const data = await res.json()
      setResult(data)
    } catch (e) {
      setError('检查失败: ' + e.message)
    } finally {
      setRunning(false)
    }
  }

  // 按 category 分组
  const grouped = {}
  if (result?.checks) {
    for (const c of result.checks) {
      const cat = c.category || 'config'
      if (!grouped[cat]) grouped[cat] = []
      grouped[cat].push(c)
    }
  }

  return (
    <div style={S.panel}>
      {/* 标题 + 操作 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>系统健康检查</div>
          <div style={{ fontSize: 11, color: '#475569' }}>检测连接、传感器、AI 和配置状态</div>
        </div>
        <button
          style={{ ...S.btnRun, marginLeft: 'auto' }}
          onClick={handleRun}
          disabled={running}
        >
          {running ? '检查中…' : '▶ 运行检查'}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '8px 12px', borderRadius: 7,
          background: 'rgba(239,68,68,.1)',
          border: '1px solid rgba(239,68,68,.3)',
          color: '#f87171', fontSize: 12,
        }}>
          {error}
        </div>
      )}

      {/* 健康分 */}
      {result && (
        <div style={{
          ...S.card,
          display: 'flex', alignItems: 'center', gap: 20,
          flexShrink: 0,
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{
              fontSize: 52, fontWeight: 800,
              color: scoreColor(result.score ?? 0),
              lineHeight: 1,
              textShadow: `0 0 20px ${scoreColor(result.score ?? 0)}66`,
            }}>
              {result.score ?? '?'}
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>健康分</div>
          </div>
          <div style={{ flex: 1 }}>
            {/* 进度条 */}
            <div style={{ height: 8, borderRadius: 99, background: 'rgba(255,255,255,.06)', overflow: 'hidden', marginBottom: 10 }}>
              <div style={{
                height: '100%',
                width: `${result.score ?? 0}%`,
                borderRadius: 99,
                background: `linear-gradient(90deg, ${scoreColor(result.score ?? 0)}aa, ${scoreColor(result.score ?? 0)})`,
                transition: 'width .5s ease',
                boxShadow: `0 0 8px ${scoreColor(result.score ?? 0)}55`,
              }} />
            </div>
            <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
              {['ok', 'warn', 'fail'].map(s => {
                const cnt = (result.checks || []).filter(c => c.status === s).length
                const { icon, color } = statusIcon(s)
                return (
                  <span key={s} style={{ color }}>
                    {icon} {cnt}
                  </span>
                )
              })}
            </div>
            {result.summary && (
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>{result.summary}</div>
            )}
          </div>
        </div>
      )}

      {/* 检查结果列表 */}
      {result && Object.keys(grouped).length > 0 && (
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {Object.entries(grouped).map(([cat, checks]) => (
            <div key={cat} style={{ ...S.card, marginBottom: 10 }}>
              <div style={S.sectionTitle}>
                {CATEGORY_ICONS[cat] || '•'} {CATEGORY_LABELS[cat] || cat}
              </div>
              {checks.map((c, i) => {
                const { icon, color } = statusIcon(c.status)
                return (
                  <div key={i} style={S.checkRow(c.status)}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>{icon}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 12, color: '#e2e8f0' }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{c.message}</div>
                      {c.fix_hint && (
                        <div style={{
                          fontSize: 11, color: '#fbbf24',
                          marginTop: 4, fontStyle: 'italic',
                        }}>
                          💡 {c.fix_hint}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}

      {/* 空态 */}
      {!result && !running && !error && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column', gap: 12, color: '#334155',
        }}>
          <div style={{ fontSize: 48 }}>🩺</div>
          <div style={{ fontSize: 13 }}>点击"运行检查"开始系统诊断</div>
        </div>
      )}

      {running && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column', gap: 12, color: '#94a3b8',
        }}>
          <div style={{ fontSize: 36, animation: 'spin 1s linear infinite' }}>⚙️</div>
          <div style={{ fontSize: 13 }}>正在运行健康检查…</div>
        </div>
      )}
    </div>
  )
}
