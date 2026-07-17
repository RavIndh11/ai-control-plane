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
  pendingAction?: any;
  timestamp: string;
}

interface AIBOMAsset {
  asset_id: string;
  name: string;
  type: string;
  location: string;
  status: string;
  risk_level: string;
  risk_factors: string[];
}

interface TopologyNode {
  id: string;
  label: string;
  type: string;
  status: string;
  details: string;
}

interface TopologyLink {
  source: string;
  target: string;
  label: string;
}

// --- Preloaded/Simulated Mock Data ---
const INITIAL_CONTROLS: Control[] = [
  { control_id: 'SOC2-CC-6.1', name: 'Access Control Security', description: 'Ensure authorized access to assets and model APIs.', status: 'action_required', evidence_count: 0 },
  { control_id: 'GDPR-Art-32', name: 'Security of Processing', description: 'Implement pseudonymization, data encryption, and masking.', status: 'action_required', evidence_count: 0 },
  { control_id: 'EU-AI-Act-Art-9', name: 'Risk Management System', description: 'Identify and mitigate safety, toxicity, and alignment risks.', status: 'action_required', evidence_count: 0 }
];

const MOCK_AIBOM: AIBOMAsset[] = [
  { asset_id: 'ast_endpoint_01', name: 'Developer Workstation (user_default)', type: 'developer_endpoint', location: 'LAN Client Host IP', status: 'active', risk_level: 'medium', risk_factors: ['policy_violation_in_history'] },
  { asset_id: 'ast_orchestrator_01', name: 'Agent Orchestrator (LangGraph Core)', type: 'autonomous_agent', location: 'Kubernetes Cluster Pod', status: 'active', risk_level: 'high', risk_factors: ['unapproved_tool_execution_intercepted'] },
  { asset_id: 'ast_gateway_01', name: 'LiteLLM API Gateway Router', type: 'ai_gateway_proxy', location: 'Kubernetes Service (Port 4000)', status: 'active', risk_level: 'info', risk_factors: [] },
  { asset_id: 'ast_llm_01', name: 'External Ollama Model Runner', type: 'llm_model_runtime', location: 'LAN Server IP (Port 11434)', status: 'active', risk_level: 'info', risk_factors: [] },
  { asset_id: 'ast_qdrant_01', name: 'Qdrant Vector Database', type: 'vector_datastore', location: 'Kubernetes StatefulSet (Port 6333)', status: 'active', risk_level: 'info', risk_factors: [] }
];

const MOCK_NODES: TopologyNode[] = [
  { id: 'user', label: 'User Browser', type: 'endpoint', status: 'danger', details: 'LAN User Session (Role: tenant-user)' },
  { id: 'dashboard', label: 'Dashboard Console', type: 'app', status: 'safe', details: 'React UI Console (Port 30082)' },
  { id: 'orchestrator', label: 'Agent Orchestrator', type: 'app', status: 'danger', details: 'LangGraph Orchestration Pod (Port 8001)' },
  { id: 'governance', label: 'Governance Engine', type: 'app', status: 'safe', details: 'FastAPI Auditing Pod (Port 8000)' },
  { id: 'postgres', label: 'PostgreSQL Database', type: 'database', status: 'safe', details: 'Audits & Checkpoints Storage (Port 5432)' },
  { id: 'qdrant', label: 'Qdrant Vector DB', type: 'database', status: 'safe', details: 'Knowledge Vectors Storage (Port 6333)' },
  { id: 'litellm', label: 'LiteLLM Gateway', type: 'runtime', status: 'safe', details: 'Model Gateway Router (Port 4000)' },
  { id: 'ollama', label: 'External Ollama Node', type: 'runtime', status: 'safe', details: 'LAN Model Runner Machine (Port 11434)' }
];

const MOCK_LINKS: TopologyLink[] = [
  { source: 'user', target: 'dashboard', label: 'HTTPS' },
  { source: 'dashboard', target: 'orchestrator', label: 'REST API' },
  { source: 'orchestrator', target: 'postgres', label: 'SQL' },
  { source: 'orchestrator', target: 'governance', label: 'GRC webhook' },
  { source: 'governance', target: 'postgres', label: 'SQL' },
  { source: 'orchestrator', target: 'qdrant', label: 'gRPC' },
  { source: 'orchestrator', target: 'litellm', label: 'REST API' },
  { source: 'litellm', target: 'ollama', label: 'External bridge' }
];

function App() {
  // Navigation & Tenant States
  const [activeTab, setActiveTab] = useState<'dashboard' | 'aibom' | 'topology' | 'playground'>('dashboard');
  const [selectedTenant, setSelectedTenant] = useState<string>('tenant-acme');
  const [isLive, setIsLive] = useState<boolean>(false);
  const [isCheckingConnection, setIsCheckingConnection] = useState<boolean>(true);

  // Compliance Data States
  const [controls, setControls] = useState<Control[]>(INITIAL_CONTROLS);
  const [evidenceLogs, setEvidenceLogs] = useState<Evidence[]>([]);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // AI-SPM Platform States
  const [aibomAssets, setAibomAssets] = useState<AIBOMAsset[]>([]);
  const [topologyNodes, setTopologyNodes] = useState<TopologyNode[]>(MOCK_NODES);
  const [topologyLinks, setTopologyLinks] = useState<TopologyLink[]>(MOCK_LINKS);
  const [aibomSearchQuery, setAibomSearchQuery] = useState<string>('');
  const [hoveredNode, setHoveredNode] = useState<TopologyNode | null>(null);

  // Agent Chat Playground States
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({});
  const [inputText, setInputText] = useState<string>('');
  const [isSending, setIsSending] = useState<boolean>(false);
  const [pendingAction, setPendingAction] = useState<any | null>(null);

  // --- API Base URLs ---
  const GOV_API = window.location.hostname === 'localhost' 
    ? 'http://localhost:8000' 
    : `${window.location.protocol}//${window.location.hostname}:30080`;
  const ORCH_API = window.location.hostname === 'localhost' 
    ? 'http://localhost:8001' 
    : `${window.location.protocol}//${window.location.hostname}:30081`;

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
      // 1. Fetch compliance status
      const res = await fetch(`${GOV_API}/api/v1/compliance/status`, {
        headers: { 
          'X-Tenant-ID': selectedTenant,
          'X-User-Role': 'tenant-admin' 
        }
      });
      const data = await res.json();
      
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

      // 2. Fetch AI-BOM Inventory
      const bomRes = await fetch(`${GOV_API}/api/v1/compliance/ai-bom`, {
        headers: { 
          'X-Tenant-ID': selectedTenant,
          'X-User-Role': 'tenant-admin' 
        }
      });
      const bomData = await bomRes.json();
      setAibomAssets(bomData.assets);

      // 3. Fetch Topology Graph Network
      const topRes = await fetch(`${GOV_API}/api/v1/compliance/topology`, {
        headers: { 
          'X-Tenant-ID': selectedTenant,
          'X-User-Role': 'tenant-admin' 
        }
      });
      const topData = await topRes.json();
      setTopologyNodes(topData.nodes);
      setTopologyLinks(topData.links);

    } catch (err) {
      console.error('Failed fetching live dashboard details', err);
    }
  };

  // Populate mock configurations for simulation mode
  const loadSimulatedData = () => {
    setControls(INITIAL_CONTROLS);
    setAibomAssets(MOCK_AIBOM);
    setTopologyNodes(MOCK_NODES);
    setTopologyLinks(MOCK_LINKS);
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
        setPendingAction(null);
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
      setPendingAction(null);
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
        
        if (data.status === 'action_required') {
          // Action intercepted (HITL)
          setPendingAction(data.output.pending_action);
          const blockMsg: ChatMessage = {
            id: `msg_${Date.now() + 1}`,
            sender: 'system',
            text: `⚠️ INTERCEPTED: Agent requested high-risk execution: ${data.output.pending_action.tool}`,
            steps: data.output.steps_executed,
            pendingAction: data.output.pending_action,
            timestamp: new Date().toLocaleTimeString()
          };
          setMessages(prev => ({
            ...prev,
            [activeThreadId]: [...(prev[activeThreadId] || []), blockMsg]
          }));
        } else {
          // Normal complete response
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
        }
        
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

        // Simulated Interrupt (HITL Tool Intercept)
        if (lowerText.includes('delete') || lowerText.includes('run command') || lowerText.includes('destroy')) {
          const action = {
            tool: 'terminal_executor',
            arguments: { command: text }
          };
          setPendingAction(action);
          const blockMsg: ChatMessage = {
            id: `msg_${Date.now() + 1}`,
            sender: 'system',
            text: `⚠️ INTERCEPTED: Agent requested high-risk execution: ${action.tool}`,
            steps: ['guardrail_check', 'agent_reasoning', 'governance_shield', 'governance_shield_interrupt'],
            pendingAction: action,
            timestamp: new Date().toLocaleTimeString()
          };
          setMessages(prev => ({
            ...prev,
            [activeThreadId]: [...(prev[activeThreadId] || []), blockMsg]
          }));
          setIsSending(false);
          return;
        }

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

          // Update Asset and Node status
          setTopologyNodes(prev => prev.map(n => n.id === 'user' ? { ...n, status: 'danger' } : n));
          setAibomAssets(prev => prev.map(a => a.asset_id === 'ast_endpoint_01' ? { ...a, risk_level: 'medium', risk_factors: ['policy_violation_in_history'] } : a));

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
      }, 800);
    }
  };

  // --- Submit User Decision on Intercepted Tool call (HITL) ---
  const handleHITLDecision = async (approve: boolean) => {
    if (!activeThreadId || !pendingAction) return;
    setIsSending(true);

    if (isLive) {
      try {
        const res = await fetch(`${ORCH_API}/api/v1/threads/${activeThreadId}/runs`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': selectedTenant
          },
          body: JSON.stringify({ approve_action: approve })
        });
        const data = await res.json();
        
        const decisionMsg: ChatMessage = {
          id: `msg_${Date.now()}`,
          sender: 'system',
          text: `Action ${approve ? 'APPROVED' : 'REJECTED'} by administrator. Executing resolution...`,
          timestamp: new Date().toLocaleTimeString()
        };

        const agentMsg: ChatMessage = {
          id: `msg_${Date.now() + 1}`,
          sender: approve ? 'agent' : 'system',
          text: data.output.response,
          isSafe: approve,
          steps: data.output.steps_executed,
          timestamp: new Date().toLocaleTimeString()
        };

        setMessages(prev => ({
          ...prev,
          [activeThreadId]: [...(prev[activeThreadId] || []), decisionMsg, agentMsg]
        }));
        setPendingAction(null);
        fetchLiveDashboardData();
      } catch (err) {
        console.error(err);
      } finally {
        setIsSending(false);
      }
    } else {
      // Simulated HITL Resolution
      setTimeout(() => {
        const decisionMsg: ChatMessage = {
          id: `msg_${Date.now()}`,
          sender: 'system',
          text: `Action ${approve ? 'APPROVED' : 'REJECTED'} by administrator. Executing resolution...`,
          timestamp: new Date().toLocaleTimeString()
        };

        const responseText = approve 
          ? `Success: Action '${pendingAction.tool}' approved and executed.`
          : `Action blocked: Execution of tool '${pendingAction.tool}' rejected by admin.`;

        const agentMsg: ChatMessage = {
          id: `msg_${Date.now() + 1}`,
          sender: approve ? 'agent' : 'system',
          text: responseText,
          isSafe: approve,
          steps: ['guardrail_check', 'agent_reasoning', 'governance_shield', approve ? 'governance_shield_executed' : 'governance_shield_rejected'],
          timestamp: new Date().toLocaleTimeString()
        };

        // GRC Engine Update for Agent Action audit
        const timestamp = new Date().toISOString();
        const evidenceId = `ev_${Math.random().toString(36).substr(2, 9)}`;
        const newEvidence: Evidence = {
          evidence_id: evidenceId,
          control_id: 'EU-AI-Act-Art-9',
          source_component: 'agent-orchestrator',
          event_type: 'agent_action_audit',
          severity: approve ? 'info' : 'high',
          payload: {
            tool: pendingAction.tool,
            decision: approve ? 'approved' : 'rejected'
          },
          minio_object_path: `tenants/${selectedTenant}/evidence/${timestamp.substring(0, 10)}/${evidenceId}.json`,
          created_at: timestamp
        };

        setEvidenceLogs(prev => [newEvidence, ...prev]);

        // Update Node Status
        setTopologyNodes(prev => prev.map(n => n.id === 'orchestrator' ? { ...n, status: approve ? 'safe' : 'danger' } : n));
        setAibomAssets(prev => prev.map(a => a.asset_id === 'ast_orchestrator_01' ? { ...a, risk_level: approve ? 'info' : 'high', risk_factors: approve ? [] : ['unapproved_tool_execution_intercepted'] } : a));

        setControls(prev => prev.map(c => {
          if (c.control_id === 'EU-AI-Act-Art-9') {
            return { ...c, status: 'compliant', evidence_count: c.evidence_count + 1 };
          }
          return c;
        }));

        setMessages(prev => ({
          ...prev,
          [activeThreadId]: [...(prev[activeThreadId] || []), decisionMsg, agentMsg]
        }));
        setPendingAction(null);
        setIsSending(false);
      }, 600);
    }
  };

  // Filter logs by search query
  const filteredLogs = evidenceLogs.filter(log => {
    const searchLower = searchQuery.toLowerCase();
    return (
      log.control_id.toLowerCase().includes(searchLower) ||
      log.source_component.toLowerCase().includes(searchLower) ||
      log.event_type.toLowerCase().includes(searchLower) ||
      log.severity.toLowerCase().includes(searchLower) ||
      JSON.stringify(log.payload).toLowerCase().includes(searchLower)
    );
  });

  // Filter assets by search query
  const filteredAssets = aibomAssets.filter(asset => {
    const searchLower = aibomSearchQuery.toLowerCase();
    return (
      asset.asset_id.toLowerCase().includes(searchLower) ||
      asset.name.toLowerCase().includes(searchLower) ||
      asset.type.toLowerCase().includes(searchLower) ||
      asset.location.toLowerCase().includes(searchLower)
    );
  });

  // Coordinates for rendering the nodes statically on the SVG canvas
  const nodePositions: Record<string, { x: number; y: number }> = {
    user: { x: 80, y: 150 },
    dashboard: { x: 260, y: 80 },
    orchestrator: { x: 260, y: 220 },
    governance: { x: 480, y: 80 },
    postgres: { x: 700, y: 80 },
    qdrant: { x: 480, y: 320 },
    litellm: { x: 480, y: 200 },
    ollama: { x: 700, y: 200 }
  };

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
            <div className="logo-text">Manifold AI-SPM</div>
          </div>

          <nav className="nav-links">
            <button 
              className={`nav-button ${activeTab === 'dashboard' ? 'active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              📊 Compliance Dashboard
            </button>
            <button 
              className={`nav-button ${activeTab === 'aibom' ? 'active' : ''}`}
              onClick={() => setActiveTab('aibom')}
            >
              📦 AI-BOM Inventory
            </button>
            <button 
              className={`nav-button ${activeTab === 'topology' ? 'active' : ''}`}
              onClick={() => setActiveTab('topology')}
            >
              🌐 Topology Map
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
            <h1>
              {activeTab === 'dashboard' && 'Compliance Operations'}
              {activeTab === 'aibom' && 'AI Bill of Materials (AI-BOM)'}
              {activeTab === 'topology' && 'Asset Topology Map'}
              {activeTab === 'playground' && 'Interactive Agent Graph'}
            </h1>
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

        {/* 📊 TAB 1: COMPLIANCE DASHBOARD */}
        {activeTab === 'dashboard' && (
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
        )}

        {/* 📦 TAB 2: AI-BOM INVENTORY */}
        {activeTab === 'aibom' && (
          <section className="logs-container">
            <div className="logs-header">
              <h2 className="section-title" style={{ margin: 0 }}>AI Bill of Materials (AI-BOM) Inventory</h2>
              <input 
                type="text" 
                placeholder="Filter assets..." 
                className="logs-search" 
                value={aibomSearchQuery}
                onChange={(e) => setAibomSearchQuery(e.target.value)}
              />
            </div>
            
            <table className="logs-table">
              <thead>
                <tr>
                  <th>Asset ID</th>
                  <th>Asset Name</th>
                  <th>Vector Type</th>
                  <th>Location</th>
                  <th>Risk Level</th>
                  <th>Risk Factors</th>
                </tr>
              </thead>
              <tbody>
                {filteredAssets.map(asset => (
                  <tr key={asset.asset_id}>
                    <td><span className="control-id" style={{ fontSize: '0.8rem' }}>{asset.asset_id}</span></td>
                    <td style={{ fontWeight: 600 }}>{asset.name}</td>
                    <td>{asset.type.replace('_', ' ')}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{asset.location}</td>
                    <td>
                      <span className={`severity-badge ${asset.risk_level}`}>
                        {asset.risk_level}
                      </span>
                    </td>
                    <td>
                      {asset.risk_factors.length === 0 ? (
                        <span style={{ color: 'var(--color-success)', fontSize: '0.85rem' }}>✓ Secure</span>
                      ) : (
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {asset.risk_factors.map(factor => (
                            <span key={factor} className="severity-badge critical" style={{ fontSize: '0.7rem', textTransform: 'none' }}>
                              {factor.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {/* 🌐 TAB 3: TOPOLOGY MAP */}
        {activeTab === 'topology' && (
          <section className="logs-container" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h2 className="section-title" style={{ margin: 0 }}>Cluster Asset & Data Flow Topology</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '20px', height: '480px' }}>
              
              {/* Topology SVG Canvas */}
              <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '12px', overflow: 'hidden', position: 'relative' }}>
                <svg width="100%" height="100%" viewBox="0 0 850 450">
                  <defs>
                    <marker id="arrow" viewBox="0 0 10 10" refX="24" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(255,255,255,0.15)" />
                    </marker>
                    <filter id="glow-safe" x="-20%" y="-20%" width="140%" height="140%">
                      <feGaussianBlur stdDeviation="4" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                    <filter id="glow-danger" x="-20%" y="-20%" width="140%" height="140%">
                      <feGaussianBlur stdDeviation="6" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                  </defs>

                  {/* Connection Lines (Links) */}
                  {topologyLinks.map((link, idx) => {
                    const from = nodePositions[link.source];
                    const to = nodePositions[link.target];
                    if (!from || !to) return null;
                    return (
                      <g key={idx}>
                        <line 
                          x1={from.x} 
                          y1={from.y} 
                          x2={to.x} 
                          y2={to.y} 
                          stroke="rgba(255, 255, 255, 0.15)" 
                          strokeWidth="2"
                          strokeDasharray="5,5"
                          markerEnd="url(#arrow)"
                        />
                        <text 
                          x={(from.x + to.x) / 2} 
                          y={(from.y + to.y) / 2 - 5}
                          fill="var(--text-secondary)"
                          fontSize="10"
                          textAnchor="middle"
                        >
                          {link.label}
                        </text>
                      </g>
                    );
                  })}

                  {/* Render Nodes */}
                  {topologyNodes.map(node => {
                    const pos = nodePositions[node.id];
                    if (!pos) return null;
                    const isDanger = node.status === 'danger';
                    return (
                      <g 
                        key={node.id} 
                        transform={`translate(${pos.x}, ${pos.y})`}
                        style={{ cursor: 'pointer' }}
                        onMouseEnter={() => setHoveredNode(node)}
                        onMouseLeave={() => setHoveredNode(null)}
                      >
                        <circle 
                          r="16" 
                          fill={isDanger ? 'var(--color-danger)' : 'rgba(16, 185, 129, 0.2)'}
                          stroke={isDanger ? '#f87171' : 'var(--color-success)'}
                          strokeWidth="2"
                          filter={isDanger ? 'url(#glow-danger)' : 'url(#glow-safe)'}
                          className={isDanger ? 'pulse-node' : ''}
                        />
                        <text 
                          y="32" 
                          fill="var(--text-primary)" 
                          fontSize="11" 
                          fontWeight="600"
                          textAnchor="middle"
                        >
                          {node.label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </div>

              {/* Node Inspector Panel */}
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <h3>Node Inspector</h3>
                {hoveredNode ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>{hoveredNode.label}</div>
                    <div>Type: <span className="control-id" style={{ fontSize: '0.8rem' }}>{hoveredNode.type}</span></div>
                    <div>Status: 
                      <span className={`severity-badge ${hoveredNode.status === 'danger' ? 'critical' : 'info'}`} style={{ marginLeft: '6px' }}>
                        {hoveredNode.status === 'danger' ? 'Vulnerable / Alert' : 'Secure'}
                      </span>
                    </div>
                    <div style={{ marginTop: '10px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                      {hoveredNode.details}
                    </div>
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                    Hover over any network node inside the topology map to inspect its running details and active alert flags.
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* 🤖 TAB 4: AGENT PLAYGROUND */}
        {activeTab === 'playground' && (
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
                    onClick={() => {
                      setActiveThreadId(t.thread_id);
                      const tMsgs = messages[t.thread_id] || [];
                      const lastMsg = tMsgs[tMsgs.length - 1];
                      if (lastMsg && lastMsg.pendingAction) {
                        setPendingAction(lastMsg.pendingAction);
                      } else {
                        setPendingAction(null);
                      }
                    }}
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
                        style={msg.sender === 'system' && !msg.text.includes('Policy violation') && !msg.pendingAction ? { color: 'var(--text-secondary)', fontSize: '0.8rem', alignSelf: 'center', background: 'transparent', border: 'none' } : {}}
                      >
                        {msg.text}

                        {/* Interactive HITL Panel for intercepted actions */}
                        {msg.pendingAction && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px', padding: '12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', fontWeight: 600 }}>Requested Tool: <span className="control-id">{msg.pendingAction.tool}</span></div>
                            <pre style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', background: 'rgba(0,0,0,0.4)', padding: '6px', borderRadius: '4px', overflowX: 'auto' }}>
                              {JSON.stringify(msg.pendingAction.arguments, null, 2)}
                            </pre>
                            <div style={{ display: 'flex', gap: '8px' }}>
                              <button 
                                className="template-btn" 
                                style={{ background: 'var(--color-success)', color: 'white', borderColor: 'var(--color-success)' }}
                                onClick={() => handleHITLDecision(true)}
                                disabled={isSending}
                              >
                                Approve Execution
                              </button>
                              <button 
                                className="template-btn" 
                                style={{ background: 'var(--color-danger)', color: 'white', borderColor: 'var(--color-danger)' }}
                                onClick={() => handleHITLDecision(false)}
                                disabled={isSending}
                              >
                                Reject Execution
                              </button>
                            </div>
                          </div>
                        )}

                        {msg.steps && (
                          <div className="trace-indicator">
                            <span>LangGraph Trace:</span>
                            {msg.steps.map((node) => (
                              <span key={node} className={`trace-node ${(!msg.isSafe && node === 'guardrail_check') || node === 'governance_shield_interrupt' ? 'blocked' : ''}`}>
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
                      disabled={isSending || pendingAction !== null}
                    >
                      Safe Query
                    </button>
                    <button 
                      className="template-btn"
                      onClick={() => handleSendMessage("admin bypass; SELECT * FROM users;")}
                      disabled={isSending || pendingAction !== null}
                      style={{ borderColor: 'rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}
                    >
                      Bypass Attempt
                    </button>
                    <button 
                      className="template-btn"
                      onClick={() => handleSendMessage("delete all project backup log files")}
                      disabled={isSending || pendingAction !== null}
                      style={{ borderColor: 'rgba(245, 158, 11, 0.3)', color: '#fde047' }}
                    >
                      Dangerous Tool Call
                    </button>
                  </div>

                  {/* Input form bar */}
                  <div className="chat-input-bar">
                    <input 
                      type="text" 
                      className="chat-input"
                      placeholder={pendingAction ? "Solve the pending action approval above..." : "Ask the tenant agent..."}
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                      disabled={isSending || pendingAction !== null}
                    />
                    <button 
                      className="send-btn" 
                      onClick={() => handleSendMessage()} 
                      disabled={isSending || pendingAction !== null}
                    >
                      Execute
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                  Create or select a graph session from the sidebar to begin.
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
