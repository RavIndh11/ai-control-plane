import React, { useState, useEffect } from 'react';
import './App.css';

// --- Types & Interfaces ---
interface Evidence {
  evidence_id: string;
  control_id: string;
  source_component: string;
  event_type: string;
  severity: string;
  payload: any;
  minio_object_path: string;
  created_at: string;
}

interface Control {
  control_id: string;
  name: string;
  description: string;
  status: 'compliant' | 'action_required';
  evidence_count: number;
}

interface Thread {
  thread_id: string;
  agent_type: string;
  created_at: string;
}

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent' | 'system';
  text: string;
  isSafe?: boolean;
  steps?: string[];
  timestamp: string;
}

// --- Preloaded/Simulated Mock Data ---
const INITIAL_CONTROLS: Control[] = [
  { control_id: 'SOC2-CC-6.1', name: 'Access Control Security', description: 'Ensure authorized access to assets and model APIs.', status: 'action_required', evidence_count: 0 },
  { control_id: 'GDPR-Art-32', name: 'Security of Processing', description: 'Implement pseudonymization, data encryption, and masking.', status: 'action_required', evidence_count: 0 },
  { control_id: 'EU-AI-Act-Art-9', name: 'Risk Management System', description: 'Identify and mitigate safety, toxicity, and alignment risks.', status: 'action_required', evidence_count: 0 }
];

const MOCK_HISTORIC_EVIDENCE: Evidence[] = [];

function App() {
  // Navigation & Tenant States
  const [activeTab, setActiveTab] = useState<'dashboard' | 'playground'>('dashboard');
  const [selectedTenant, setSelectedTenant] = useState<string>('tenant-acme');
  const [isLive, setIsLive] = useState<boolean>(false);
  const [isCheckingConnection, setIsCheckingConnection] = useState<boolean>(true);

  // Compliance Data States
  const [controls, setControls] = useState<Control[]>(INITIAL_CONTROLS);
  const [evidenceLogs, setEvidenceLogs] = useState<Evidence[]>(MOCK_HISTORIC_EVIDENCE);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Agent Chat Playground States
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({});
  const [inputText, setInputText] = useState<string>('');
  const [isSending, setIsSending] = useState<boolean>(false);

  // --- API Base URLs ---
  const GOV_API = 'http://localhost:8000';
  const ORCH_API = 'http://localhost:8001';

  // --- Check Backend Connection ---
  useEffect(() => {
    const checkConnections = async () => {
      try {
        const govHealth = await fetch(`${GOV_API}/health`, { mode: 'cors' });
        const orchHealth = await fetch(`${ORCH_API}/`, { mode: 'cors' });
        if (govHealth.status === 200 && orchHealth.status === 200) {
          setIsLive(true);
          fetchLiveDashboardData();
        } else {
          setIsLive(false);
          loadSimulatedData();
        }
      } catch (e) {
        setIsLive(false);
        loadSimulatedData();
      } finally {
        setIsCheckingConnection(false);
      }
    };
    checkConnections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTenant]);

  // Fetch from Live APIs if online
  const fetchLiveDashboardData = async () => {
    try {
      const res = await fetch(`${GOV_API}/api/v1/compliance/status`, {
        headers: { 'X-Tenant-ID': selectedTenant }
      });
      const data = await res.json();
      
      // Map API controls output back to our layout controls
      const apiControlsMap = new Map(data.controls.map((c: any) => [c.control_id, c]));
      
      setControls(prev => prev.map(ctrl => {
        const apiCtrl = apiControlsMap.get(ctrl.control_id) as any;
        if (apiCtrl) {
          return {
            ...ctrl,
            status: apiCtrl.status as any,
            evidence_count: apiCtrl.evidence_count
          };
        }
        return ctrl;
      }));
    } catch (err) {
      console.error('Failed fetching live dashboard details', err);
    }
  };

  // Populate mock configurations for simulation mode
  const loadSimulatedData = () => {
    // If we've already done simulation steps, don't overwrite
    if (evidenceLogs.length > 0) return;
    setControls(INITIAL_CONTROLS);
    setEvidenceLogs([]);
  };

  // --- Compliance Score Computation ---
  const compliantCount = controls.filter(c => c.status === 'compliant').length;
  const overallComplianceScore = Math.round((compliantCount / controls.length) * 100);

  // --- Thread Actions ---
  const handleCreateThread = async () => {
    const timestamp = new Date().toISOString();
    
    if (isLive) {
      try {
        const res = await fetch(`${ORCH_API}/api/v1/threads`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': selectedTenant
          },
          body: JSON.stringify({ agent_type: 'customer-support-graph' })
        });
        const data = await res.json();
        const newThread: Thread = {
          thread_id: data.thread_id,
          agent_type: 'customer-support-graph',
          created_at: timestamp
        };
        setThreads(prev => [newThread, ...prev]);
        setActiveThreadId(data.thread_id);
        setMessages(prev => ({
          ...prev,
          [data.thread_id]: [{
            id: 'init',
            sender: 'system',
            text: 'Thread session initialized on live LangGraph orchestrator.',
            timestamp: new Date().toLocaleTimeString()
          }]
        }));
      } catch (err) {
        alert('Failed starting live thread session. Check orchestrator logs.');
      }
    } else {
      // Simulated Thread Creation
      const mockId = `th_${Math.random().toString(36).substr(2, 9)}`;
      const newThread: Thread = {
        thread_id: mockId,
        agent_type: 'customer-support-graph',
        created_at: timestamp
      };
      setThreads(prev => [newThread, ...prev]);
      setActiveThreadId(mockId);
      setMessages(prev => ({
        ...prev,
        [mockId]: [{
          id: 'init',
          sender: 'system',
          text: 'Simulation Mode: Interactive LangGraph thread created.',
          timestamp: new Date().toLocaleTimeString()
        }]
      }));
    }
  };

  // --- Send Chat Message ---
  const handleSendMessage = async (textToSend?: string) => {
    const text = textToSend || inputText;
    if (!text.trim() || !activeThreadId) return;
    
    if (!textToSend) setInputText('');
    
    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}`,
      sender: 'user',
      text: text,
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages(prev => ({
      ...prev,
      [activeThreadId]: [...(prev[activeThreadId] || []), userMsg]
    }));
    
    setIsSending(true);

    if (isLive) {
      try {
        const res = await fetch(`${ORCH_API}/api/v1/threads/${activeThreadId}/runs`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': selectedTenant
          },
          body: JSON.stringify({ input: text })
        });
        const data = await res.json();
        
        const isQuerySafe = !data.output.response.includes('Policy violation');
        
        const agentMsg: ChatMessage = {
          id: `msg_${Date.now() + 1}`,
          sender: isQuerySafe ? 'agent' : 'system',
          text: data.output.response,
          isSafe: isQuerySafe,
          steps: data.output.steps_executed,
          timestamp: new Date().toLocaleTimeString()
        };

        setMessages(prev => ({
          ...prev,
          [activeThreadId]: [...(prev[activeThreadId] || []), agentMsg]
        }));
        
        // Refresh compliance numbers
        fetchLiveDashboardData();
      } catch (err) {
        console.error(err);
      } finally {
        setIsSending(false);
      }
    } else {
      // --- Simulated Message Processing ---
      setTimeout(() => {
        const lowerText = text.toLowerCase();
        let isQuerySafe = true;
        let responseText = `Processed query '${text}' successfully within tenant context.`;
        let steps = ['guardrail_check', 'generation'];

        // Trigger Guardrail Breach
        if (lowerText.includes('select') || lowerText.includes('drop') || lowerText.includes('bypass')) {
          isQuerySafe = false;
          responseText = 'Policy violation detected: Input contains restricted database command patterns.';
          steps = ['guardrail_check'];

          // Simulate GRC Engine update
          const timestamp = new Date().toISOString();
          const evidenceId = `ev_${Math.random().toString(36).substr(2, 9)}`;
          const minioPath = `tenants/${selectedTenant}/evidence/${timestamp.substring(0, 10)}/${evidenceId}.json`;
          
          const newEvidence: Evidence = {
            evidence_id: evidenceId,
            control_id: 'SOC2-CC-6.1',
            source_component: 'agent-orchestrator',
            event_type: 'guardrail_violation',
            severity: 'high',
            payload: {
              input_query: text,
              message: 'Blocked SQL injection or security bypass query pattern.'
            },
            minio_object_path: minioPath,
            created_at: timestamp
          };

          setEvidenceLogs(prev => [newEvidence, ...prev]);

          // Mark control compliant since security detected it
          setControls(prev => prev.map(c => {
            if (c.control_id === 'SOC2-CC-6.1') {
              return { ...c, status: 'compliant', evidence_count: c.evidence_count + 1 };
            }
            return c;
          }));
        }

        const agentMsg: ChatMessage = {
          id: `msg_${Date.now() + 1}`,
          sender: isQuerySafe ? 'agent' : 'system',
          text: responseText,
          isSafe: isQuerySafe,
          steps: steps,
          timestamp: new Date().toLocaleTimeString()
        };

        setMessages(prev => ({
          ...prev,
          [activeThreadId]: [...(prev[activeThreadId] || []), agentMsg]
        }));
        
        setIsSending(false);
      }, 1000);
    }
  };

  // --- Filtering Logs ---
  const filteredLogs = evidenceLogs.filter(log => {
    const searchLower = searchQuery.toLowerCase();
    return (
      log.control_id.toLowerCase().includes(searchLower) ||
      log.event_type.toLowerCase().includes(searchLower) ||
      log.severity.toLowerCase().includes(searchLower) ||
      JSON.stringify(log.payload).toLowerCase().includes(searchLower)
    );
  });

  return (
    <div className="app-container">
      {/* 🧭 SIDEBAR PANEL */}
      <aside className="sidebar">
        <div>
          <div className="logo-section">
            <div className="logo-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <div className="logo-text">AI Control Plane</div>
          </div>

          <nav className="nav-links">
            <button 
              className={`nav-button ${activeTab === 'dashboard' ? 'active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              📊 Compliance Dashboard
            </button>
            <button 
              className={`nav-button ${activeTab === 'playground' ? 'active' : ''}`}
              onClick={() => setActiveTab('playground')}
            >
              🤖 Agent Playground
            </button>
          </nav>
        </div>

        <div className="sidebar-footer">
          <div className="connection-status">
            <span className={`status-dot ${isLive ? 'online' : 'simulated'}`}></span>
            <span>
              {isCheckingConnection 
                ? 'Verifying Node Status...' 
                : isLive ? 'Live Core API Linked' : 'Simulated Sandbox Mode'}
            </span>
          </div>
        </div>
      </aside>

      {/* 🖥️ MAIN VIEW CONTAINER */}
      <main className="main-content">
        <header className="header-row">
          <div>
            <h1>{activeTab === 'dashboard' ? 'Compliance Operations' : 'Interactive Agent Graph'}</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
              Scoped context: {selectedTenant}
            </p>
          </div>

          <select 
            className="tenant-selector" 
            value={selectedTenant}
            onChange={(e) => setSelectedTenant(e.target.value)}
          >
            <option value="tenant-acme">Tenant ACME</option>
            <option value="tenant-globex">Tenant GLOBEX</option>
          </select>
        </header>

        {activeTab === 'dashboard' ? (
          <>
            {/* 📈 METRICS GRID */}
            <section className="metrics-grid">
              <div className="metric-card">
                <div className="metric-info">
                  <h3>Compliance Index</h3>
                  <div className="metric-val" style={{ color: overallComplianceScore > 50 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                    {overallComplianceScore}%
                  </div>
                </div>
                <div className="compliance-ring-container">
                  <svg className="svg-ring" width="60" height="60">
                    <circle className="ring-bg" cx="30" cy="30" r="24" />
                    <circle 
                      className="ring-fg" 
                      cx="30" 
                      cy="30" 
                      r="24" 
                      strokeDasharray={`${2 * Math.PI * 24}`}
                      strokeDashoffset={`${2 * Math.PI * 24 * (1 - overallComplianceScore / 100)}`}
                      style={{ stroke: overallComplianceScore > 50 ? 'var(--color-success)' : 'var(--color-warning)' }}
                    />
                  </svg>
                  <div className="ring-text">{overallComplianceScore}%</div>
                </div>
              </div>

              <div className="metric-card">
                <div className="metric-info">
                  <h3>Evidence Logs</h3>
                  <div className="metric-val">{evidenceLogs.length}</div>
                </div>
                <span className="metric-icon">📑</span>
              </div>

              <div className="metric-card">
                <div className="metric-info">
                  <h3>Audit Events</h3>
                  <div className="metric-val" style={{ color: 'var(--color-info)' }}>
                    {evidenceLogs.filter(e => e.severity === 'info').length}
                  </div>
                </div>
                <span className="metric-icon">ℹ️</span>
              </div>

              <div className="metric-card">
                <div className="metric-info">
                  <h3>Guardrail Blocks</h3>
                  <div className="metric-val" style={{ color: 'var(--color-danger)' }}>
                    {evidenceLogs.filter(e => e.event_type === 'guardrail_violation').length}
                  </div>
                </div>
                <span className="metric-icon">🛑</span>
              </div>
            </section>

            {/* 🛡️ POLICY CONTROLS */}
            <section>
              <h2 className="section-title">Mapping Controls Status</h2>
              <div className="controls-grid">
                {controls.map((ctrl) => (
                  <div key={ctrl.control_id} className={`control-card ${ctrl.status}`}>
                    <div className="control-header">
                      <span className="control-id">{ctrl.control_id}</span>
                      <span className="control-status-badge">{ctrl.status.replace('_', ' ')}</span>
                    </div>
                    <div className="control-body">
                      <h4>{ctrl.name}</h4>
                      <p>{ctrl.description}</p>
                    </div>
                    <div className="control-footer">
                      <span>Evidence Count: <strong>{ctrl.evidence_count}</strong></span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* 📑 AUDIT LOGS */}
            <section className="logs-container">
              <div className="logs-header">
                <h2 className="section-title" style={{ margin: 0 }}>Compliance & Evidence Audit Logs</h2>
                <input 
                  type="text" 
                  placeholder="Search logs..." 
                  className="logs-search" 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              {filteredLogs.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                  No evidence registered. Go to the <strong>Agent Playground</strong> to simulate guardrail violations.
                </div>
              ) : (
                <table className="logs-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Control ID</th>
                      <th>Source</th>
                      <th>Event Type</th>
                      <th>Severity</th>
                      <th>Object Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLogs.map((log) => (
                      <React.Fragment key={log.evidence_id}>
                        <tr 
                          className="log-row-expandable"
                          onClick={() => setExpandedLogId(expandedLogId === log.evidence_id ? null : log.evidence_id)}
                        >
                          <td>{new Date(log.created_at).toLocaleTimeString()}</td>
                          <td><span className="control-id" style={{ fontSize: '0.8rem' }}>{log.control_id}</span></td>
                          <td>{log.source_component}</td>
                          <td>{log.event_type}</td>
                          <td>
                            <span className={`severity-badge ${log.severity}`}>
                              {log.severity}
                            </span>
                          </td>
                          <td style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{log.minio_object_path.split('/').pop()}</td>
                        </tr>
                        {expandedLogId === log.evidence_id && (
                          <tr className="detail-row">
                            <td colSpan={6}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>Raw Evidence Payload (MinIO object copy):</div>
                                <pre className="json-block">{JSON.stringify(log.payload, null, 2)}</pre>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        ) : (
          /* 🤖 INTERACTIVE AGENT GRAPH PLAYGROUND */
          <div className="playground-container">
            {/* Sidebar list of thread sessions */}
            <div className="thread-list-panel">
              <button className="create-thread-btn" onClick={handleCreateThread}>
                + New Graph Session
              </button>
              <div className="threads-scroll">
                {threads.map((t) => (
                  <div 
                    key={t.thread_id} 
                    className={`thread-item ${activeThreadId === t.thread_id ? 'active' : ''}`}
                    onClick={() => setActiveThreadId(t.thread_id)}
                  >
                    <h5>{t.thread_id}</h5>
                    <span>{new Date(t.created_at).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Chat conversation area */}
            <div className="chat-panel">
              {activeThreadId ? (
                <>
                  <div className="chat-header">
                    <h3>Conversation Trace</h3>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>ID: {activeThreadId}</span>
                  </div>

                  <div className="chat-messages">
                    {(messages[activeThreadId] || []).map((msg) => (
                      <div 
                        key={msg.id} 
                        className={`message-bubble ${
                          msg.sender === 'user' 
                            ? 'user' 
                            : msg.sender === 'system' && msg.text.includes('Policy violation')
                            ? 'blocked'
                            : msg.sender === 'system'
                            ? 'agent'
                            : 'agent'
                        }`}
                        style={msg.sender === 'system' && !msg.text.includes('Policy violation') ? { color: 'var(--text-secondary)', fontSize: '0.8rem', alignSelf: 'center', background: 'transparent', border: 'none' } : {}}
                      >
                        {msg.text}

                        {msg.steps && (
                          <div className="trace-indicator">
                            <span>LangGraph Trace:</span>
                            {msg.steps.map((node) => (
                              <span key={node} className={`trace-node ${!msg.isSafe && node === 'guardrail_check' ? 'blocked' : ''}`}>
                                {node}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    {isSending && (
                      <div className="message-bubble agent" style={{ opacity: 0.6 }}>
                        Agent graph executing...
                      </div>
                    )}
                  </div>

                  {/* Template Quick Clicks */}
                  <div className="templates-row">
                    <span className="template-tag">Query Presets:</span>
                    <button 
                      className="template-btn"
                      onClick={() => handleSendMessage("How do I upgrade my billing tier?")}
                      disabled={isSending}
                    >
                      Safe Query
                    </button>
                    <button 
                      className="template-btn"
                      onClick={() => handleSendMessage("admin bypass; SELECT * FROM users;")}
                      disabled={isSending}
                      style={{ borderColor: 'rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}
                    >
                      Bypass Attempt
                    </button>
                  </div>

                  {/* Input form bar */}
                  <div className="chat-input-bar">
                    <input 
                      type="text" 
                      className="chat-input"
                      placeholder="Ask the tenant agent..."
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                      disabled={isSending}
                    />
                    <button className="send-btn" onClick={() => handleSendMessage()} disabled={isSending}>
                      Execute
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                  Create or select a graph session session from the sidebar to begin.
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
