/**
 * ChatPage — AutoGen Chatbot UI
 *
 * SSE subscription flow:
 *   1. POST /api/chat/sessions            → {sessionId}
 *   2. GET  /api/chat/{sessionId}/stream  → EventSource (stays open)
 *   3. POST /api/chat/{sessionId}/send    → queue user message
 *   4. DELETE /api/chat/{sessionId}       → close session on exit
 *
 * Event types from SSE stream:
 *   ready       — agent is waiting for input (enables the send button)
 *   message     — assistant text reply
 *   tool_call   — MCP tool being invoked (shown as a collapsible badge)
 *   tool_result — MCP tool response (shown inside the badge)
 *   error       — unrecoverable error
 *   done        — session ended
 */

import { useEffect, useRef, useState, useCallback } from 'react';

const API = '/api/chat';

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function timestamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function tryParseJson(str) {
  try { return JSON.parse(str); } catch { return str; }
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function ToolCallBadge({ event }) {
  const [open, setOpen] = useState(false);
  const args    = event.args   ? JSON.stringify(event.args,    null, 2) : '—';
  const result  = event.result ? JSON.stringify(tryParseJson(event.result), null, 2) : null;

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs font-mono bg-sky-500/10 dark:bg-sky-400/10
                   border border-sky-300/40 dark:border-sky-500/30 text-sky-700 dark:text-sky-300
                   px-2.5 py-1 rounded-full hover:bg-sky-500/20 transition-colors"
      >
        <span className={`inline-block w-2 h-2 rounded-full ${result ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse'}`} />
        🔧 {event.tool}
        <span className="text-sky-400/70 ml-1">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="mt-1 ml-2 rounded-lg border border-sky-200/40 dark:border-sky-700/40
                        bg-slate-50 dark:bg-slate-900/50 text-xs font-mono overflow-x-auto">
          <div className="px-3 py-2 border-b border-sky-100/50 dark:border-sky-800/50 text-sky-600 dark:text-sky-400 font-semibold">
            Args
          </div>
          <pre className="px-3 py-2 text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{args}</pre>
          {result && (
            <>
              <div className="px-3 py-2 border-t border-emerald-100/50 dark:border-emerald-800/50 text-emerald-600 dark:text-emerald-400 font-semibold">
                Result
              </div>
              <pre className="px-3 py-2 text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

/* ── Message renderer ─────────────────────────────────────────────────────── */

function Message({ msg }) {
  const isUser = msg.role === 'user';

  if (msg.type === 'tool_group') {
    return (
      <div className="flex justify-start mb-3">
        <div className="max-w-[80%]">
          <div className="text-[10px] text-slate-400 dark:text-slate-500 mb-1 pl-1">MCP tools</div>
          {msg.tools.map((t, i) => <ToolCallBadge key={i} event={t} />)}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex mb-4 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center text-white text-sm font-bold mr-2 shrink-0 mt-0.5">
          🤖
        </div>
      )}
      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-brand-600 text-white rounded-tr-sm'
              : 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 shadow-sm border border-slate-100 dark:border-slate-700 rounded-tl-sm'
          }`}
        >
          {msg.content}
        </div>
        <span className="text-[10px] text-slate-400 dark:text-slate-500 mt-1 px-1">{msg.time}</span>
      </div>
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-sm ml-2 shrink-0 mt-0.5">
          👤
        </div>
      )}
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */

export default function ChatPage() {
  const [messages,    setMessages]    = useState([]);
  const [input,       setInput]       = useState('');
  const [sessionId,   setSessionId]   = useState(null);
  const [ready,       setReady]       = useState(false);   // agent waiting for input
  const [typing,      setTyping]      = useState(false);   // agent processing
  const [ended,       setEnded]       = useState(false);
  const [error,       setError]       = useState(null);
  const [connecting,  setConnecting]  = useState(false);

  const bottomRef    = useRef(null);
  const esRef        = useRef(null);        // EventSource
  const pendingTool  = useRef(null);        // accumulate tool_call waiting for tool_result
  const toolGroupRef = useRef([]);          // current batch of tool calls
  const endedRef     = useRef(false);       // ref mirror of ended — readable inside closures

  /* ── Scroll to bottom on new messages ─────────────────────────────────── */
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  /* ── Append a display message ──────────────────────────────────────────── */
  const addMsg = useCallback((msg) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), time: timestamp(), ...msg }]);
  }, []);

  /* ── Flush accumulated tool group as one message ───────────────────────── */
  const flushToolGroup = useCallback(() => {
    if (toolGroupRef.current.length === 0) return;
    addMsg({ type: 'tool_group', role: 'agent', tools: [...toolGroupRef.current] });
    toolGroupRef.current = [];
    pendingTool.current  = null;
  }, [addMsg]);

  /* ── SSE event handler ─────────────────────────────────────────────────── */
  const handleEvent = useCallback((event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    switch (data.type) {
      case 'ready':
        flushToolGroup();
        setTyping(false);
        setReady(true);
        break;

      case 'message':
        flushToolGroup();
        setTyping(false);
        addMsg({ type: 'text', role: 'assistant', content: data.content });
        break;

      case 'tool_call':
        setTyping(true);
        // Start a new pending tool entry
        pendingTool.current = { tool: data.tool, args: data.args, result: null };
        toolGroupRef.current.push(pendingTool.current);
        // Trigger a re-render so the badge shows immediately (amber dot)
        setMessages(prev => [...prev]);
        break;

      case 'tool_result':
        // Attach result to the last pending tool
        if (pendingTool.current) {
          pendingTool.current.result = data.content;
        }
        setMessages(prev => [...prev]);   // re-render to show green dot
        break;

      case 'error':
        flushToolGroup();
        setTyping(false);
        // Mark session as ended — an SSE error always precedes a 'done' event,
        // so this prevents the subsequent onerror callback from overwriting
        // the real error message with the generic "Connection lost" text.
        endedRef.current = true;
        setEnded(true);
        setError(data.content);
        addMsg({ type: 'text', role: 'assistant', content: `⚠️ ${data.content}` });
        break;

      case 'done':
        flushToolGroup();
        setTyping(false);
        setReady(false);
        endedRef.current = true;
        setEnded(true);
        esRef.current?.close();
        break;

      default:
        break;
    }
  }, [addMsg, flushToolGroup]);

  /* ── Start session ─────────────────────────────────────────────────────── */
  const startSession = useCallback(async () => {
    // Tear down any existing EventSource before resetting state.
    // Without this, the old EventSource keeps reconnecting and its onerror
    // fires AFTER endedRef is reset to false, triggering a false "Connection lost".
    if (esRef.current) {
      esRef.current.onmessage = null;
      esRef.current.onerror   = null;
      esRef.current.close();
      esRef.current = null;
    }

    setConnecting(true);
    setError(null);
    setEnded(false);
    endedRef.current = false;
    setMessages([]);
    toolGroupRef.current = [];
    pendingTool.current  = null;

    try {
      const res = await fetch(`${API}/sessions`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ firstMessage: 'Hello! I need help planning a shipment.' }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { sessionId: sid } = await res.json();
      setSessionId(sid);

      // Open SSE stream
      const es = new EventSource(`${API}/${sid}/stream`);
      esRef.current = es;
      es.onmessage = handleEvent;
      es.onerror   = () => {
        // Defer the check by one task so any queued onmessage callbacks
        // (including the 'done' event) run first.  Without this, the browser
        // fires onerror for the server-side connection close before it
        // delivers the final 'done' message, making a clean shutdown look
        // like a real failure.
        setTimeout(() => {
          if (endedRef.current) return;              // session ended cleanly
          if (es.readyState === EventSource.CLOSED) return;  // we called es.close()
          es.close();
          setError('Connection lost. Try starting a new session.');
        }, 0);
      };

      setConnecting(false);
      setTyping(true);   // agent will respond to the greeting
    } catch (err) {
      setError(err.message);
      setConnecting(false);
    }
  }, [handleEvent, ended]);

  /* ── Auto-start on mount ───────────────────────────────────────────────── */
  useEffect(() => {
    startSession();
    return () => { esRef.current?.close(); };
  }, []); // eslint-disable-line

  /* ── Send message ──────────────────────────────────────────────────────── */
  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || !ready) return;

    setInput('');
    setReady(false);
    setTyping(true);
    addMsg({ type: 'text', role: 'user', content: text });

    try {
      await fetch(`${API}/${sessionId}/send`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ message: text }),
      });
    } catch (err) {
      setError(err.message);
      setTyping(false);
    }

    if (text.toLowerCase() in { exit: 1, quit: 1, bye: 1, goodbye: 1 }) {
      setEnded(true);
    }
  }, [input, sessionId, ready, addMsg]);

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const endSession = async () => {
    if (sessionId) {
      await fetch(`${API}/${sessionId}`, { method: 'DELETE' }).catch(() => {});
    }
    endedRef.current = true;
    esRef.current?.close();
    setEnded(true);
    setReady(false);
    addMsg({ type: 'text', role: 'assistant', content: 'Session ended. Start a new one below.' });
  };

  /* ── Suggested prompts ─────────────────────────────────────────────────── */
  const SUGGESTIONS = [
    'What is the capacity of warehouse WH-001?',
    'Find the best route from WH-001 to postal 10001, US for 500 kg',
    'Which carriers serve Chicago to New York for 500 kg?',
    'Get a STANDARD quote from carrier DHL Express',
  ];

  const useSuggestion = (s) => { setInput(s); };

  /* ── Render ────────────────────────────────────────────────────────────── */
  const canSend = ready && !ended && input.trim().length > 0;

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] max-w-3xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-slate-700 mb-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
            🤖 AutoGen Chatbot
          </h1>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
            AutoGen AssistantAgent · MCP tools · SSE subscription
            {sessionId && (
              <span className="ml-2 font-mono opacity-60">{sessionId.slice(0, 8)}</span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {!ended && sessionId && (
            <button
              onClick={endSession}
              className="text-xs px-3 py-1.5 rounded-lg border border-red-200 dark:border-red-800
                         text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors"
            >
              End session
            </button>
          )}
          {(ended || error) && (
            <button
              onClick={startSession}
              className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors"
            >
              New session
            </button>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className={`text-xs px-3 py-1.5 rounded-lg mb-3 font-medium transition-all ${
        connecting ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300' :
        ended      ? 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400' :
        error      ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400' :
        ready      ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300' :
                     'bg-sky-50 dark:bg-sky-900/20 text-sky-700 dark:text-sky-300'
      }`}>
        {connecting  ? '⏳ Connecting to agent…'
        : ended      ? '🔴 Session ended'
        : error      ? `⚠️ ${error}`
        : ready      ? '🟢 Agent ready — type your message'
        : typing     ? '⚙️ Agent is thinking…'
        :              '⏳ Waiting for agent…'}
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-1 space-y-1">

        {/* Empty state with suggestions */}
        {messages.length === 0 && !connecting && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <div className="text-5xl">🚚</div>
            <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs">
              Ask about warehouse capacity, routes, carriers, or quotes.
            </p>
            <div className="flex flex-col gap-2 w-full max-w-sm">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => useSuggestion(s)}
                  className="text-left text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700
                             text-slate-600 dark:text-slate-300 hover:border-brand-400 hover:bg-brand-50
                             dark:hover:bg-brand-900/20 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => <Message key={msg.id} msg={msg} />)}

        {typing && (
          <div className="flex justify-start mb-2">
            <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center text-white text-sm font-bold mr-2 mt-0.5">
              🤖
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-2xl rounded-tl-sm shadow-sm border border-slate-100 dark:border-slate-700">
              <TypingIndicator />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="mt-3 flex gap-2 items-end">
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            ended   ? 'Session ended — start a new one'
            : ready ? 'Type a message… (Enter to send, Shift+Enter for newline)'
            :         'Waiting for agent…'
          }
          disabled={!ready || ended}
          rows={1}
          className="flex-1 resize-none rounded-xl border border-slate-200 dark:border-slate-700
                     bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100
                     px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all
                     max-h-32 overflow-y-auto"
          style={{ minHeight: '46px' }}
        />
        <button
          onClick={sendMessage}
          disabled={!canSend}
          className="h-[46px] px-4 rounded-xl bg-brand-600 text-white font-medium text-sm
                     hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed
                     transition-colors shrink-0"
        >
          Send
        </button>
      </div>

      <p className="text-[10px] text-center text-slate-400 dark:text-slate-600 mt-2">
        Type <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">exit</code> to end the session · Events stream via SSE
      </p>
    </div>
  );
}
