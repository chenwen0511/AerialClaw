import { useState, useRef, useEffect } from 'react';
import { io } from 'socket.io-client';

const COLORS = {
  bg: 'rgba(15,23,42,.7)',
  bgSolid: '#0f172b',
  accent: '#00d4ff',
  success: '#4ade80',
  error: '#f87171',
  warn: '#fbbf24',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  border: 'rgba(255,255,255,.08)',
};

const S = {
  panel: {
    background: COLORS.bg,
    backdropFilter: 'blur(20px)',
    borderRadius: 16,
    border: '1px solid ' + COLORS.border,
    color: COLORS.text,
    fontFamily: "'Inter','SF Pro Display',system-ui,sans-serif",
    padding: 24,
    minHeight: 520,
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    marginBottom: 20,
  },
  title: {
    fontSize: 22,
    fontWeight: 700,
    margin: 0,
    color: '#fff',
  },
  subtitle: {
    fontSize: 13,
    color: COLORS.textDim,
    marginTop: 4,
  },
  tabs: {
    display: 'flex',
    gap: 4,
    marginBottom: 20,
    background: 'rgba(255,255,255,.04)',
    borderRadius: 10,
    padding: 4,
  },
  tab: (active) => ({
    flex: 1,
    padding: '8px 0',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
    transition: 'all .2s',
    background: active ? COLORS.accent : 'transparent',
    color: active ? '#000' : COLORS.textDim,
  }),
  body: {
    flex: 1,
    overflowY: 'auto',
    minHeight: 0,
  },
  btn: (color) => ({
    padding: '10px 20px',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 14,
    background: color,
    color: color === COLORS.warn ? '#000' : '#fff',
    transition: 'opacity .2s',
  }),
  stepCard: {
    background: 'rgba(255,255,255,.04)',
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
    border: '1px solid ' + COLORS.border,
  },
  stepIter: {
    fontSize: 11,
    fontWeight: 700,
    color: COLORS.accent,
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  stepThink: {
    fontSize: 13,
    color: COLORS.textDim,
    marginBottom: 6,
    fontStyle: 'italic',
  },
  stepTool: {
    fontSize: 12,
    color: COLORS.warn,
    marginBottom: 4,
  },
  stepResult: (ok) => ({
    fontSize: 12,
    padding: '6px 10px',
    borderRadius: 6,
    background: ok ? 'rgba(74,222,128,.1)' : 'rgba(248,113,113,.1)',
    color: ok ? COLORS.success : COLORS.error,
    marginTop: 6,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  }),
  chatBubble: (isUser) => ({
    maxWidth: '75%',
    padding: '10px 14px',
    borderRadius: 12,
    marginBottom: 8,
    fontSize: 14,
    lineHeight: 1.5,
    alignSelf: isUser ? 'flex-end' : 'flex-start',
    background: isUser ? COLORS.accent : 'rgba(255,255,255,.06)',
    color: isUser ? '#000' : COLORS.text,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  }),
  chatWrap: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    minHeight: 0,
  },
  chatMessages: {
    flex: 1,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    paddingBottom: 12,
  },
  chatInput: {
    display: 'flex',
    gap: 8,
    marginTop: 12,
  },
  input: {
    flex: 1,
    padding: '10px 14px',
    borderRadius: 8,
    border: '1px solid ' + COLORS.border,
    background: 'rgba(255,255,255,.05)',
    color: COLORS.text,
    fontSize: 14,
    outline: 'none',
  },
  scoreWrap: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'column',
    padding: 30,
  },
  scoreCircle: (score) => ({
    width: 120,
    height: 120,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 36,
    fontWeight: 800,
    border: '4px solid ' + (score >= 80 ? COLORS.success : score >= 50 ? COLORS.warn : COLORS.error),
    color: score >= 80 ? COLORS.success : score >= 50 ? COLORS.warn : COLORS.error,
    marginBottom: 12,
  }),
  listItem: (type) => ({
    padding: '8px 12px',
    borderRadius: 6,
    marginBottom: 6,
    fontSize: 13,
    background: type === 'issue' ? 'rgba(248,113,113,.08)' : 'rgba(74,222,128,.08)',
    color: type === 'issue' ? COLORS.error : COLORS.success,
    borderLeft: '3px solid ' + (type === 'issue' ? COLORS.error : COLORS.success),
  }),
  sectionLabel: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: 'uppercase',
    color: COLORS.textDim,
    marginBottom: 8,
    marginTop: 16,
  },
};

function DoctorPanel() {
  const [tab, setTab] = useState('auto');
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([]);
  const [status, setStatus] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [diagResult, setDiagResult] = useState(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const stepsEndRef = useRef(null);
  const chatEndRef = useRef(null);
  const socketRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    const socket = io({ path: '/socket.io', transports: ['websocket'] });
    socketRef.current = socket;
    socket.on('doctor_step', (step) => {
      setSteps((prev) => [...prev, step]);
    });
    return () => {
      socket.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (stepsEndRef.current) stepsEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  useEffect(() => {
    if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  const startRun = async () => {
    setRunning(true);
    setSteps([]);
    setStatus(null);
    try {
      await fetch('/api/doctor/run', { method: 'POST' });
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch('/api/doctor/status');
          const data = await res.json();
          setStatus(data);
          if (data.state === 'done' || data.state === 'error' || data.state === 'stopped') {
            setRunning(false);
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (e) { /* ignore */ }
      }, 2000);
    } catch (e) {
      setRunning(false);
    }
  };

  const stopRun = async () => {
    try {
      await fetch('/api/doctor/stop', { method: 'POST' });
    } catch (e) { /* ignore */ }
    setRunning(false);
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const sendChat = async () => {
    const msg = chatInput.trim();
    if (!msg || chatLoading) return;
    const newHistory = [...chatHistory, { role: 'user', content: msg }];
    setChatHistory(newHistory);
    setChatInput('');
    setChatLoading(true);
    try {
      const res = await fetch('/api/doctor/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, history: newHistory }),
      });
      const data = await res.json();
      setChatHistory((prev) => [...prev, { role: 'assistant', content: data.reply || data.message || 'No response' }]);
    } catch (e) {
      setChatHistory((prev) => [...prev, { role: 'assistant', content: 'Error: ' + e.message }]);
    }
    setChatLoading(false);
  };

  const runDiagnose = async () => {
    setDiagLoading(true);
    setDiagResult(null);
    try {
      const res = await fetch('/api/doctor/diagnose');
      const data = await res.json();
      setDiagResult(data);
    } catch (e) {
      setDiagResult({ score: 0, issues: ['Failed to run diagnose: ' + e.message], passed: [] });
    }
    setDiagLoading(false);
  };

  const handleChatKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  };

  const renderAuto = () => (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <button style={S.btn(COLORS.accent)} onClick={startRun} disabled={running}>
          {running ? '⏳ 运行中...' : '🚀 开始'}
        </button>
        <button style={S.btn(COLORS.error)} onClick={stopRun} disabled={!running}>
          ⏹ 停止
        </button>
        {status && (
          <span style={{ fontSize: 12, color: COLORS.textDim, alignSelf: 'center' }}>
            状态: {status.state || 'unknown'}
          </span>
        )}
      </div>
      <div style={S.body}>
        {steps.length === 0 && !running && (
          <div style={{ textAlign: 'center', color: COLORS.textDim, padding: 40, fontSize: 14 }}>
            点击 "🚀 开始" 启动 Doctor Agent 自主诊断
          </div>
        )}
        {steps.map((step, i) => (
          <div key={i} style={S.stepCard}>
            <div style={S.stepIter}>Iteration #{step.iteration || i + 1}</div>
            {step.thinking && <div style={S.stepThink}>💭 {step.thinking}</div>}
            {step.tool && (
              <div style={S.stepTool}>
                🔧 {step.tool}
                {step.args ? ` (${typeof step.args === 'string' ? step.args : JSON.stringify(step.args)})` : ''}
              </div>
            )}
            {step.result !== undefined && (
              <div style={S.stepResult(step.success !== false)}>
                {step.success === false ? '❌ ' : step.summary ? '📋 ' : '✅ '}
                {step.summary || step.result || (step.success === false ? 'Error' : 'Done')}
              </div>
            )}
          </div>
        ))}
        <div ref={stepsEndRef} />
      </div>
    </div>
  );

  const renderChat = () => (
    <div style={S.chatWrap}>
      <div style={S.chatMessages}>
        {chatHistory.length === 0 && (
          <div style={{ textAlign: 'center', color: COLORS.textDim, padding: 40, fontSize: 14 }}>
            与 Doctor Agent 对话，询问设备状态或故障排查建议
          </div>
        )}
        {chatHistory.map((msg, i) => (
          <div key={i} style={S.chatBubble(msg.role === 'user')}>
            {msg.content}
          </div>
        ))}
        {chatLoading && (
          <div style={S.chatBubble(false)}>
            <span style={{ opacity: 0.6 }}>思考中...</span>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>
      <div style={S.chatInput}>
        <input
          style={S.input}
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={handleChatKeyDown}
          placeholder="输入问题..."
          disabled={chatLoading}
        />
        <button style={S.btn(COLORS.accent)} onClick={sendChat} disabled={chatLoading || !chatInput.trim()}>
          发送
        </button>
      </div>
    </div>
  );

  const renderDiagnose = () => (
    <div>
      <div style={{ marginBottom: 16 }}>
        <button style={S.btn(COLORS.accent)} onClick={runDiagnose} disabled={diagLoading}>
          {diagLoading ? '⏳ 诊断中...' : '🔍 开始诊断'}
        </button>
      </div>
      {!diagResult && !diagLoading && (
        <div style={{ textAlign: 'center', color: COLORS.textDim, padding: 40, fontSize: 14 }}>
          点击 "🔍 开始诊断" 快速检查系统状态
        </div>
      )}
      {diagResult && (
        <div>
          <div style={S.scoreWrap}>
            <div style={S.scoreCircle(diagResult.score)}>
              {diagResult.score}
            </div>
            <div style={{ fontSize: 14, color: COLORS.textDim }}>/ 100</div>
          </div>
          {diagResult.issues && diagResult.issues.length > 0 && (
            <div>
              <div style={S.sectionLabel}>⚠️ 问题列表</div>
              {diagResult.issues.map((item, i) => (
                <div key={i} style={S.listItem('issue')}>
                  {item}
                </div>
              ))}
            </div>
          )}
          {diagResult.passed && diagResult.passed.length > 0 && (
            <div>
              <div style={S.sectionLabel}>✅ 通过项目</div>
              {diagResult.passed.map((item, i) => (
                <div key={i} style={S.listItem('passed')}>
                  {item}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );

  const tabs = [
    { key: 'auto', label: '自主模式' },
    { key: 'chat', label: '对话' },
    { key: 'diagnose', label: '快速诊断' },
  ];

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <h2 style={S.title}>🩺 Doctor Agent</h2>
        <div style={S.subtitle}>设备接入工程师</div>
      </div>
      <div style={S.tabs}>
        {tabs.map((t) => (
          <button key={t.key} style={S.tab(tab === t.key)} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {tab === 'auto' && renderAuto()}
        {tab === 'chat' && renderChat()}
        {tab === 'diagnose' && renderDiagnose()}
      </div>
    </div>
  );
}

export default DoctorPanel;
