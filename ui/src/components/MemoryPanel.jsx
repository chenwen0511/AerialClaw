/**
 * MemoryPanel.jsx — 记忆系统面板
 */
import { useState, useEffect, useCallback } from 'react'

const LAYER_META = {
  working:  { label: '工作记忆',   icon: '⚡', color: '#00d4ff', desc: '当前任务上下文' },
  episodic: { label: '情景记忆',   icon: '📖', color: '#a855f7', desc: '历史任务片段' },
  skill:    { label: '技能记忆',   icon: '🧩', color: '#f59e0b', desc: '学到的操作经验' },
  world:    { label: '世界知识',   icon: '🌍', color: '#22c55e', desc: '环境与地图信息' },
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
  sectionTitle: {
    fontSize: 11, fontWeight: 700, color: '#00d4ff',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 10,
  },
  searchInput: {
    width: '100%', boxSizing: 'border-box',
    background: 'rgba(255,255,255,.05)',
    border: '1px solid rgba(0,212,255,.2)',
    borderRadius: 6,
    color: '#e2e8f0', fontSize: 12, padding: '7px 11px',
    outline: 'none',
  },
}

function LayerCard({ layerKey, meta, count }) {
  return (
    <div style={{
      flex: 1,
      background: `rgba(${hexToRgb(meta.color)},.07)`,
      border: `1px solid rgba(${hexToRgb(meta.color)},.25)`,
      borderRadius: 8,
      padding: '12px 10px',
      textAlign: 'center',
      minWidth: 0,
    }}>
      <div style={{ fontSize: 22, marginBottom: 6 }}>{meta.icon}</div>
      <div style={{ fontSize: 24, fontWeight: 800, color: meta.color, lineHeight: 1 }}>{count ?? '—'}</div>
      <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 4, fontWeight: 600 }}>{meta.label}</div>
      <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>{meta.desc}</div>
    </div>
  )
}

function hexToRgb(color) {
  const map = {
    '#00d4ff': '0,212,255',
    '#a855f7': '168,85,247',
    '#f59e0b': '245,158,11',
    '#22c55e': '34,197,94',
  }
  return map[color] || '148,163,184'
}

function MemoryEntry({ entry }) {
  const layerMeta = LAYER_META[entry.layer] || {}
  return (
    <div style={{
      padding: '9px 12px',
      background: 'rgba(255,255,255,.03)',
      border: '1px solid rgba(255,255,255,.06)',
      borderRadius: 7,
      marginBottom: 6,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{layerMeta.icon || '•'}</span>
        <span style={{
          fontSize: 10, padding: '1px 8px', borderRadius: 99,
          background: `rgba(${hexToRgb(layerMeta.color || '#94a3b8')},.12)`,
          border: `1px solid rgba(${hexToRgb(layerMeta.color || '#94a3b8')},.3)`,
          color: layerMeta.color || '#94a3b8',
          fontWeight: 600,
        }}>
          {layerMeta.label || entry.layer}
        </span>
        {entry.score != null && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#475569' }}>
            相似度 {(entry.score * 100).toFixed(0)}%
          </span>
        )}
        {entry.timestamp && (
          <span style={{ fontSize: 10, color: '#334155' }}>
            {new Date(entry.timestamp * 1000).toLocaleTimeString()}
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.5, wordBreak: 'break-all' }}>
        {typeof entry.content === 'string'
          ? entry.content
          : JSON.stringify(entry.content)}
      </div>
    </div>
  )
}

export default function MemoryPanel() {
  const [stats,    setStats]   = useState({})    // { working: N, episodic: N, ... }
  const [entries,  setEntries] = useState([])
  const [query,    setQuery]   = useState('')
  const [searching, setSearching] = useState(false)
  const [loading,  setLoading] = useState(true)

  const fetchStats = useCallback(async () => {
    try {
      const res  = await fetch('/api/memory/stats')
      const data = await res.json()
      setStats(data.layers || data || {})
    } catch (_) {}
  }, [])

  const fetchRecent = useCallback(async () => {
    setLoading(true)
    try {
      const res  = await fetch('/api/memory/recent?limit=20')
      const data = await res.json()
      setEntries(Array.isArray(data) ? data : (data.entries || data.memories || []))
    } catch (_) {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStats()
    fetchRecent()
  }, [fetchStats, fetchRecent])

  const handleSearch = async () => {
    if (!query.trim()) { fetchRecent(); return }
    setSearching(true)
    try {
      const res  = await fetch('/api/memory/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), limit: 20 }),
      })
      const data = await res.json()
      setEntries(Array.isArray(data) ? data : (data.results || data.entries || []))
    } catch (_) {}
    setSearching(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch()
  }

  const handleClearSearch = () => {
    setQuery('')
    fetchRecent()
  }

  return (
    <div style={S.panel}>
      {/* 标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>记忆系统</div>
          <div style={{ fontSize: 11, color: '#475569' }}>四层记忆 · 语义检索</div>
        </div>
        <button
          onClick={() => { fetchStats(); fetchRecent() }}
          style={{
            marginLeft: 'auto',
            background: 'transparent',
            border: '1px solid rgba(0,212,255,.2)',
            borderRadius: 6,
            color: '#00d4ff', fontSize: 11,
            padding: '4px 12px', cursor: 'pointer',
          }}
        >
          ↻ 刷新
        </button>
      </div>

      {/* 四层统计卡片 */}
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        {Object.entries(LAYER_META).map(([key, meta]) => (
          <LayerCard key={key} layerKey={key} meta={meta} count={stats[key]} />
        ))}
      </div>

      {/* 搜索框 */}
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        <input
          style={S.searchInput}
          placeholder="语义搜索记忆…（按 Enter）"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            background: 'rgba(0,212,255,.15)',
            border: '1px solid rgba(0,212,255,.35)',
            borderRadius: 6,
            color: '#00d4ff', fontSize: 12, fontWeight: 600,
            padding: '0 14px', cursor: 'pointer', flexShrink: 0,
          }}
        >
          {searching ? '…' : '搜索'}
        </button>
        {query && (
          <button
            onClick={handleClearSearch}
            style={{
              background: 'transparent',
              border: '1px solid rgba(255,255,255,.1)',
              borderRadius: 6,
              color: '#64748b', fontSize: 12,
              padding: '0 10px', cursor: 'pointer', flexShrink: 0,
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* 记忆列表 */}
      <div style={{ ...S.card, flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <div style={S.sectionTitle}>
          {query ? `搜索结果: "${query}"` : '最近记忆'}
        </div>

        {loading && (
          <div style={{ textAlign: 'center', color: '#475569', fontSize: 12, padding: 20 }}>加载中…</div>
        )}
        {!loading && entries.length === 0 && (
          <div style={{ textAlign: 'center', color: '#334155', fontSize: 12, padding: 20 }}>
            {query ? '未找到相关记忆' : '暂无记忆条目'}
          </div>
        )}
        {entries.map((entry, i) => (
          <MemoryEntry key={i} entry={entry} />
        ))}
      </div>
    </div>
  )
}
