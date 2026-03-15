/**
 * SafetyPanel.jsx — 安全体系面板
 */
import { useState, useEffect, useCallback } from 'react'

const LEVEL_META = {
  strict:     { label: '严格', icon: '🔒', color: '#f87171', bg: 'rgba(239,68,68,.1)',  border: 'rgba(239,68,68,.35)' },
  standard:   { label: '标准', icon: '🛡',  color: '#fbbf24', bg: 'rgba(245,158,11,.1)', border: 'rgba(245,158,11,.35)' },
  permissive: { label: '宽松', icon: '🚀',  color: '#4ade80', bg: 'rgba(34,197,94,.1)',  border: 'rgba(34,197,94,.35)' },
}

const GATE_META = [
  { key: 'preflight',   label: '飞行前检查', icon: '✈️' },
  { key: 'skill',       label: '技能审批',   icon: '🧩' },
  { key: 'trajectory',  label: '轨迹验证',   icon: '📍' },
  { key: 'emergency',   label: '紧急熔断',   icon: '🚨' },
]

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
  sectionTitle: {
    fontSize: 11, fontWeight: 700, color: '#00d4ff',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 10,
  },
}

function GateCard({ meta, gateData }) {
  const active  = gateData?.enabled !== false
  const blocked = gateData?.blocked ?? 0
  const passed  = gateData?.passed  ?? 0

  return (
    <div style={{
      flex: 1,
      background: active ? 'rgba(34,197,94,.06)' : 'rgba(239,68,68,.06)',
      border: `1px solid ${active ? 'rgba(34,197,94,.25)' : 'rgba(239,68,68,.25)'}`,
      borderRadius: 8,
      padding: '12px 10px',
      textAlign: 'center',
      minWidth: 0,
    }}>
      <div style={{ fontSize: 22, marginBottom: 6 }}>{meta.icon}</div>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>{meta.label}</div>
      <div style={{
        fontSize: 10, fontWeight: 700,
        color: active ? '#4ade80' : '#f87171',
        marginBottom: 6,
      }}>
        {active ? 'ACTIVE' : 'DISABLED'}
      </div>
      <div style={{ fontSize: 10, color: '#64748b' }}>
        <div>通过 {passed}</div>
        <div style={{ color: blocked > 0 ? '#fbbf24' : '#475569' }}>拦截 {blocked}</div>
      </div>
    </div>
  )
}

export default function SafetyPanel() {
  const [data,     setData]     = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [audits,   setAudits]   = useState([])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [safetyRes, auditRes] = await Promise.all([
        fetch('/api/safety/status'),
        fetch('/api/safety/audit?limit=10'),
      ])
      if (safetyRes.ok) setData(await safetyRes.json())
      if (auditRes.ok)  {
        const a = await auditRes.json()
        setAudits(Array.isArray(a) ? a : (a.logs || a.entries || []))
      }
    } catch (_) {}
    setLoading(false)
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const level    = data?.level || 'standard'
  const levelMeta = LEVEL_META[level] || LEVEL_META.standard
  const envelope = data?.envelope || {}
  const gates    = data?.gates    || {}

  const envelopeItems = [
    ['最大速度',   envelope.max_speed   != null ? `${envelope.max_speed} m/s` : '—'],
    ['最大高度',   envelope.max_altitude != null ? `${envelope.max_altitude} m`   : '—'],
    ['最低电量',   envelope.min_battery  != null ? `${envelope.min_battery}%`   : '—'],
    ['最大倾斜角', envelope.max_tilt     != null ? `${envelope.max_tilt}°`     : '—'],
  ]

  return (
    <div style={S.panel}>
      {/* 标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>安全体系</div>
          <div style={{ fontSize: 11, color: '#475569' }}>多道关卡 · 实时审计</div>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          style={{
            marginLeft: 'auto',
            background: 'transparent',
            border: '1px solid rgba(0,212,255,.2)',
            borderRadius: 6,
            color: '#00d4ff', fontSize: 11,
            padding: '4px 12px', cursor: 'pointer',
          }}
        >
          {loading ? '刷新中…' : '↻ 刷新'}
        </button>
      </div>

      {/* 当前安全等级 */}
      <div style={{
        ...S.card,
        background: levelMeta.bg,
        border: `1px solid ${levelMeta.border}`,
        display: 'flex', alignItems: 'center', gap: 14,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 32 }}>{levelMeta.icon}</span>
        <div>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>当前安全等级</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: levelMeta.color }}>
            {levelMeta.label}模式
          </div>
          {data?.description && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{data.description}</div>
          )}
        </div>
      </div>

      {/* 四道关卡 */}
      <div style={{ ...S.card, flexShrink: 0 }}>
        <div style={S.sectionTitle}>安全关卡状态</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {GATE_META.map(meta => (
            <GateCard key={meta.key} meta={meta} gateData={gates[meta.key]} />
          ))}
        </div>
      </div>

      {/* 安全包线参数 */}
      <div style={{ ...S.card, flexShrink: 0 }}>
        <div style={S.sectionTitle}>安全包线参数</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 20px' }}>
          {envelopeItems.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: '#64748b' }}>{k}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 审计日志 */}
      <div style={{ ...S.card, flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <div style={S.sectionTitle}>最近审计日志</div>
        {audits.length === 0 && (
          <div style={{ textAlign: 'center', color: '#334155', fontSize: 12, padding: '16px 0' }}>
            暂无审计记录
          </div>
        )}
        {audits.map((entry, i) => {
          const passed = entry.result === 'pass' || entry.passed === true
          return (
            <div key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              padding: '7px 0',
              borderBottom: i < audits.length - 1 ? '1px solid rgba(255,255,255,.04)' : 'none',
            }}>
              <span style={{ fontSize: 14, flexShrink: 0 }}>
                {passed ? '✅' : '🚫'}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: '#e2e8f0' }}>
                  {entry.action || entry.skill || entry.message || '未知操作'}
                </div>
                {entry.reason && (
                  <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{entry.reason}</div>
                )}
              </div>
              <div style={{ fontSize: 10, color: '#334155', flexShrink: 0 }}>
                {entry.time || entry.timestamp
                  ? new Date((entry.time || entry.timestamp) * 1000).toLocaleTimeString()
                  : ''}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
