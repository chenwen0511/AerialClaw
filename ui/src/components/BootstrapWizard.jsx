/**
 * BootstrapWizard.jsx — 首次启动引导向导
 * 三步: LLM配置 → 安全等级 → 完成
 */
import { useState } from 'react'

const S = {
  overlay: {
    position: 'fixed', inset: 0, zIndex: 9000,
    background: 'rgba(0,0,0,.85)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  card: {
    background: 'rgba(15,23,42,.98)',
    border: '1px solid rgba(0,212,255,.25)',
    borderRadius: 14,
    padding: 32,
    width: 480,
    maxWidth: '90vw',
    boxShadow: '0 0 60px rgba(0,212,255,.08)',
  },
  title: {
    fontSize: 20, fontWeight: 700, color: '#00d4ff',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 13, color: '#64748b', marginBottom: 24,
  },
  label: { fontSize: 12, color: '#94a3b8', marginBottom: 4 },
  input: {
    width: '100%', boxSizing: 'border-box',
    background: 'rgba(255,255,255,.05)',
    border: '1px solid rgba(0,212,255,.2)',
    borderRadius: 6,
    color: '#e2e8f0', fontSize: 13, padding: '8px 11px',
    outline: 'none', marginBottom: 14,
  },
  btnPrimary: {
    background: 'linear-gradient(135deg,rgba(0,212,255,.25),rgba(0,212,255,.12))',
    border: '1px solid rgba(0,212,255,.5)',
    borderRadius: 8,
    color: '#00d4ff', fontSize: 13, fontWeight: 600,
    padding: '9px 20px', cursor: 'pointer',
  },
  btnGhost: {
    background: 'transparent',
    border: '1px solid rgba(255,255,255,.1)',
    borderRadius: 8,
    color: '#64748b', fontSize: 13,
    padding: '9px 20px', cursor: 'pointer',
  },
  safetyCard: (selected, color) => ({
    flex: 1,
    background: selected ? `rgba(${color},.15)` : 'rgba(255,255,255,.03)',
    border: `2px solid ${selected ? `rgba(${color},.6)` : 'rgba(255,255,255,.08)'}`,
    borderRadius: 10,
    padding: '16px 12px',
    cursor: 'pointer',
    transition: 'all .2s ease',
    textAlign: 'center',
  }),
  dot: (active) => ({
    width: 10, height: 10, borderRadius: '50%',
    background: active ? '#00d4ff' : 'rgba(255,255,255,.15)',
    boxShadow: active ? '0 0 8px #00d4ff' : 'none',
    transition: 'all .2s',
  }),
}

const SAFETY_OPTIONS = [
  {
    key: 'strict',
    label: '严格模式',
    icon: '🔒',
    desc: '最严格安全限制，适合室内或人群密集场景',
    color: '239,68,68',
    textColor: '#f87171',
  },
  {
    key: 'standard',
    label: '标准模式',
    icon: '🛡',
    desc: '均衡安全与灵活性，推荐日常使用',
    color: '245,158,11',
    textColor: '#fbbf24',
  },
  {
    key: 'permissive',
    label: '宽松模式',
    icon: '🚀',
    desc: '较少限制，适合专业测试场景',
    color: '34,197,94',
    textColor: '#4ade80',
  },
]

export default function BootstrapWizard({ onComplete }) {
  const [step, setStep]       = useState(0)   // 0/1/2
  const [llm, setLlm]         = useState({ base_url: 'https://api.openai.com/v1', api_key: '', model: 'gpt-4o' })
  const [testing, setTesting] = useState(false)
  const [testMsg, setTestMsg] = useState(null) // { ok, text }
  const [safety, setSafety]   = useState('standard')
  const [saving, setSaving]   = useState(false)
  const [summary, setSummary] = useState(null)

  // ── Step 0: LLM 配置 ────────────────────────────────────────────────────────
  const handleTestLLM = async () => {
    if (!llm.api_key.trim()) {
      setTestMsg({ ok: false, text: '请填写 API Key' })
      return
    }
    setTesting(true)
    setTestMsg(null)
    try {
      const res  = await fetch('/api/bootstrap/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llm),
      })
      const data = await res.json()
      if (res.ok && data.ok !== false) {
        setTestMsg({ ok: true, text: data.message || '连接成功' })
        setTimeout(() => setStep(1), 800)
      } else {
        setTestMsg({ ok: false, text: data.error || data.message || '连接失败' })
      }
    } catch (e) {
      setTestMsg({ ok: false, text: '请求失败: ' + e.message })
    } finally {
      setTesting(false)
    }
  }

  // ── Step 1: 安全等级 ─────────────────────────────────────────────────────────
  const handleSaveSafety = async () => {
    setSaving(true)
    try {
      await fetch('/api/bootstrap/safety', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: safety }),
      })
      setStep(2)
      setSummary({ base_url: llm.base_url, model: llm.model, safety })
    } catch (e) {
      // 即使失败也进入下一步
      setStep(2)
      setSummary({ base_url: llm.base_url, model: llm.model, safety })
    } finally {
      setSaving(false)
    }
  }

  // ── Step 2: 完成 ─────────────────────────────────────────────────────────────
  const handleComplete = async () => {
    setSaving(true)
    try {
      await fetch('/api/bootstrap/complete', { method: 'POST' })
    } catch (_) {}
    setSaving(false)
    onComplete()
  }

  return (
    <div style={S.overlay}>
      <div style={S.card}>
        {/* 顶部 Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
          <span style={{ fontSize: 26 }}>🤖</span>
          <div>
            <div style={{ color: '#00d4ff', fontWeight: 800, fontSize: 16, letterSpacing: 2 }}>AERIALCLAW v2.0</div>
            <div style={{ color: '#475569', fontSize: 11 }}>首次启动配置向导</div>
          </div>
        </div>

        {/* Step 0: LLM 配置 */}
        {step === 0 && (
          <div>
            <div style={S.title}>步骤 1 / 3 — LLM 配置</div>
            <div style={S.subtitle}>配置 AI 驱动所需的语言模型接口</div>

            <div style={S.label}>Base URL</div>
            <input
              style={S.input}
              value={llm.base_url}
              onChange={e => setLlm(f => ({ ...f, base_url: e.target.value }))}
              placeholder="https://api.openai.com/v1"
            />

            <div style={S.label}>API Key</div>
            <input
              style={S.input}
              type="password"
              value={llm.api_key}
              onChange={e => setLlm(f => ({ ...f, api_key: e.target.value }))}
              placeholder="sk-..."
            />

            <div style={S.label}>模型</div>
            <input
              style={{ ...S.input, marginBottom: 20 }}
              value={llm.model}
              onChange={e => setLlm(f => ({ ...f, model: e.target.value }))}
              placeholder="gpt-4o"
            />

            {testMsg && (
              <div style={{
                padding: '8px 12px', borderRadius: 7, marginBottom: 16,
                background: testMsg.ok ? 'rgba(34,197,94,.12)' : 'rgba(239,68,68,.12)',
                border: `1px solid ${testMsg.ok ? 'rgba(34,197,94,.4)' : 'rgba(239,68,68,.4)'}`,
                color: testMsg.ok ? '#4ade80' : '#f87171',
                fontSize: 12,
              }}>
                {testMsg.ok ? '✅ ' : '❌ '}{testMsg.text}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                style={S.btnPrimary}
                onClick={handleTestLLM}
                disabled={testing}
              >
                {testing ? '测试中…' : '测试连接并继续 →'}
              </button>
            </div>
          </div>
        )}

        {/* Step 1: 安全等级 */}
        {step === 1 && (
          <div>
            <div style={S.title}>步骤 2 / 3 — 安全等级</div>
            <div style={S.subtitle}>选择飞行安全策略（后续可在安全面板修改）</div>

            <div style={{ display: 'flex', gap: 10, marginBottom: 24 }}>
              {SAFETY_OPTIONS.map(opt => (
                <div
                  key={opt.key}
                  style={S.safetyCard(safety === opt.key, opt.color)}
                  onClick={() => setSafety(opt.key)}
                >
                  <div style={{ fontSize: 24, marginBottom: 8 }}>{opt.icon}</div>
                  <div style={{ fontWeight: 700, fontSize: 13, color: safety === opt.key ? opt.textColor : '#e2e8f0', marginBottom: 6 }}>
                    {opt.label}
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>{opt.desc}</div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <button style={S.btnGhost} onClick={() => setStep(0)}>← 返回</button>
              <button style={S.btnPrimary} onClick={handleSaveSafety} disabled={saving}>
                {saving ? '保存中…' : '保存并继续 →'}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: 完成 */}
        {step === 2 && (
          <div>
            <div style={S.title}>步骤 3 / 3 — 配置完成</div>
            <div style={S.subtitle}>您的 AerialClaw v2.0 已就绪</div>

            <div style={{
              background: 'rgba(0,212,255,.06)',
              border: '1px solid rgba(0,212,255,.2)',
              borderRadius: 10,
              padding: 18,
              marginBottom: 24,
            }}>
              <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 10 }}>配置摘要</div>
              {summary && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[
                    ['LLM 接口', summary.base_url],
                    ['模型', summary.model],
                    ['安全等级', SAFETY_OPTIONS.find(o => o.key === summary.safety)?.label || summary.safety],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', gap: 10, fontSize: 13 }}>
                      <span style={{ color: '#475569', width: 80, flexShrink: 0 }}>{k}</span>
                      <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button style={S.btnPrimary} onClick={handleComplete} disabled={saving}>
                {saving ? '启动中…' : '🚀 开始使用'}
              </button>
            </div>
          </div>
        )}

        {/* 底部进度点 */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 28 }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={S.dot(i === step)} />
          ))}
        </div>
      </div>
    </div>
  )
}
