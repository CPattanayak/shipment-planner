/**
 * ChatPage — AutoGen Chatbot UI
 *
 * Session lifecycle:
 *   1. POST /api/chat/sessions           → {sessionId}  — create Redis entry
 *   2. POST /api/chat/{sessionId}        → SSE stream   — one turn per POST
 *   3. DELETE /api/chat/{sessionId}      — wipe Redis entry (close / unmount)
 *
 * No persistent EventSource — each user message opens a fresh fetch stream
 * that closes when the turn is done.  Redis TTL (1 h) covers abandoned tabs.
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

/** Read a fetch Response body as a stream of SSE events. */
async function* readSSE(response) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let   buffer  = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();          // keep any partial last line

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)); } catch { /* skip bad JSON */ }
      }
    }
  }
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function ToolCallBadge({ event }) {
  const [open, setOpen] = useState(false);
  const args   = event.args   ? JSON.stringify(event.args,   null, 2) : '—';
  const result = event.result ? JSON.stringify(tryParseJson(event.result), null, 2) : null;

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
            <span key={i} className="w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce"
                  style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
  );
}

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
          <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
              isUser
                  ? 'bg-brand-600 text-white rounded-tr-sm'
                  : 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 shadow-sm border border-slate-100 dark:border-slate-700 rounded-tl-sm'
          }`}>
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

const EXIT_WORDS = new Set(['exit', 'quit', 'bye', 'goodbye']);
const GREETING   = 'Hello! I need help planning a shipment.';

export default function ChatPage() {
  const [messages,   setMessages]   = useState([]);
  const [input,      setInput]      = useState('');
  const [sessionId,  setSessionId]  = useState(null);
  const [thinking,   setThinking]   = useState(false);
  const [ended,      setEnded]      = useState(false);
  const [error,      setError]      = useState(null);

  const bottomRef    = useRef(null);
  const sessionRef   = useRef(null);     // ref copy — readable inside callbacks
  const toolCallMap  = useRef({});       // call_id → tool object (for result matching)
  const toolGroupRef = useRef([]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, thinking]);

  /* ── Helpers ───────────────────────────────────────────────────────────── */

  const addMsg = useCallback((msg) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), time: timestamp(), ...msg }]);
  }, []);

  const flushToolGroup = useCallback(() => {
    if (toolGroupRef.current.length === 0) return;
    addMsg({ type: 'tool_group', role: 'agent', tools: [...toolGroupRef.current] });
    toolGroupRef.current = [];
    toolCallMap.current  = {};
  }, [addMsg]);

  /** Delete the Redis session — called on close, unmount, and browser leave. */
  const deleteSession = useCallback((sid) => {
    const id = sid ?? sessionRef.current;
    if (!id) return;
    // navigator.sendBeacon is fire-and-forget — survives tab close
    navigator.sendBeacon(`${API}/${id}/beacon`);
    // Also try fetch for normal closes (may fail if page already unloading)
    fetch(`${API}/${id}`, { method: 'DELETE' }).catch(() => {});
    sessionRef.current = null;
  }, []);

  /* ── Process one SSE event from the stream ─────────────────────────────── */

  const handleEvent = useCallback((data) => {
    switch (data.type) {
      case 'message':
        flushToolGroup();
        setThinking(false);
        addMsg({ type: 'text', role: 'assistant', content: data.content });
        break;

      case 'tool_call': {
        // Track by call_id so each result matches its own call (not just the last one)
        const toolObj = { tool: data.tool, call_id: data.call_id, args: data.args, result: null };
        toolGroupRef.current.push(toolObj);
        if (data.call_id) toolCallMap.current[data.call_id] = toolObj;
        setMessages(prev => [...prev]);   // trigger re-render (amber pulse)
        break;
      }

      case 'tool_result': {
        // Match by call_id — falls back to last tool if id missing
        const matched = data.call_id
            ? toolCallMap.current[data.call_id]
            : toolGroupRef.current[toolGroupRef.current.length - 1];
        if (matched) matched.result = data.content;
        setMessages(prev => [...prev]);   // re-render (green dot)
        break;
      }

      case 'error':
        flushToolGroup();
        setThinking(false);
        setError(data.content);
        addMsg({ type: 'text', role: 'assistant', content: `⚠️ ${data.content}` });
        break;

      case 'done':
        flushToolGroup();
        setThinking(false);
        break;

      default:
        break;
    }
  }, [addMsg, flushToolGroup]);

  /* ── Send one turn to the backend and read the streaming reply ─────────── */

  const sendTurn = useCallback(async (sid, text) => {
    setThinking(true);
    try {
      const res = await fetch(`${API}/${sid}`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail);
      }
      for await (const event of readSSE(res)) {
        handleEvent(event);
      }
    } catch (err) {
      setError(err.message);
      addMsg({ type: 'text', role: 'assistant', content: `⚠️ ${err.message}` });
    } finally {
      // Always re-enable input — guards against streams that end without 'done'
      setThinking(false);
    }
  }, [handleEvent, addMsg]);

  /* ── Start a new session ───────────────────────────────────────────────── */

  const startSession = useCallback(async () => {
    // Clean up any previous session
    deleteSession(sessionRef.current);

    setMessages([]);
    setError(null);
    setEnded(false);
    setThinking(false);
    toolGroupRef.current = [];
    toolCallMap.current  = {};

    try {
      const res = await fetch(`${API}/sessions`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      const { sessionId: sid } = await res.json();
      setSessionId(sid);
      sessionRef.current = sid;

      // Send the greeting as the first turn
      await sendTurn(sid, GREETING);
    } catch (err) {
      setError(err.message);
    }
  }, [deleteSession, sendTurn]);

  /* ── Auto-start on mount; cleanup on unmount ───────────────────────────── */

  useEffect(() => {
    startSession();

    // Delete Redis session when the tab closes or navigates away
    const onUnload = () => deleteSession(sessionRef.current);
    window.addEventListener('beforeunload', onUnload);
    return () => {
      window.removeEventListener('beforeunload', onUnload);
      deleteSession(sessionRef.current);
    };
  }, []); // eslint-disable-line

  /* ── Send a user message ───────────────────────────────────────────────── */

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || thinking || ended) return;

    setInput('');
    addMsg({ type: 'text', role: 'user', content: text });

    if (EXIT_WORDS.has(text.toLowerCase())) {
      deleteSession(sessionId);
      setEnded(true);
      addMsg({ type: 'text', role: 'assistant', content: 'Session ended. Start a new one below.' });
      return;
    }

    await sendTurn(sessionId, text);
  }, [input, sessionId, thinking, ended, addMsg, sendTurn, deleteSession]);

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const endSession = () => {
    deleteSession(sessionId);
    setSessionId(null);
    setEnded(true);
    addMsg({ type: 'text', role: 'assistant', content: 'Session ended. Start a new one below.' });
  };

  /* ── Suggestions ───────────────────────────────────────────────────────── */

  const SUGGESTIONS = [
    'What is the capacity of warehouse WH-001?',
    'Find the best route from WH-001 to postal 10001, US for 500 kg',
    'Which carriers serve Chicago to New York for 500 kg?',
    'Get a STANDARD quote from carrier DHL Express',
  ];

  const canSend = !thinking && !ended && input.trim().length > 0 && !!sessionId;

  /* ── Render ────────────────────────────────────────────────────────────── */

  return (
      <div className="flex flex-col h-[calc(100vh-10rem)] max-w-3xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-slate-700 mb-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
              🤖 AutoGen Chatbot
            </h1>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
              Redis session · MCP tools · per-turn streaming
              {sessionId && <span className="ml-2 font-mono opacity-60">{sessionId.slice(0, 8)}</span>}
            </p>
          </div>
          <div className="flex gap-2">
            {!ended && sessionId && (
                <button onClick={endSession}
                        className="text-xs px-3 py-1.5 rounded-lg border border-red-200 dark:border-red-800
                         text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors">
                  End session
                </button>
            )}
            {(ended || error) && (
                <button onClick={startSession}
                        className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors">
                  New session
                </button>
            )}
          </div>
        </div>

        {/* Status bar */}
        <div className={`text-xs px-3 py-1.5 rounded-lg mb-3 font-medium transition-all ${
            ended   ? 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400' :
                error   ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400' :
                    thinking? 'bg-sky-50 dark:bg-sky-900/20 text-sky-700 dark:text-sky-300' :
                        'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300'
        }`}>
          {ended    ? '🔴 Session ended'
              : error   ? `⚠️ ${error}`
                  : thinking ? '⚙️ Agent is thinking…'
                      :            '🟢 Ready — type your message'}
        </div>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-1 space-y-1">
          {messages.length === 0 && !thinking && (
              <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
                <div className="text-5xl">🚚</div>
                <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs">
                  Ask about warehouse capacity, routes, carriers, or quotes.
                </p>
                <div className="flex flex-col gap-2 w-full max-w-sm">
                  {SUGGESTIONS.map((s, i) => (
                      <button key={i} onClick={() => setInput(s)}
                              className="text-left text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700
                             text-slate-600 dark:text-slate-300 hover:border-brand-400 hover:bg-brand-50
                             dark:hover:bg-brand-900/20 transition-colors">
                        {s}
                      </button>
                  ))}
                </div>
              </div>
          )}

          {messages.map(msg => <Message key={msg.id} msg={msg} />)}

          {thinking && (
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
              ended    ? 'Session ended — start a new one'
                  : thinking? 'Agent is thinking…'
                      :           'Type a message… (Enter to send)'
            }
            disabled={thinking || ended || !sessionId}
            rows={1}
            className="flex-1 resize-none rounded-xl border border-slate-200 dark:border-slate-700
                     bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100
                     px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all
                     max-h-32 overflow-y-auto"
            style={{ minHeight: '46px' }}
        />
          <button onClick={sendMessage} disabled={!canSend}
                  className="h-[46px] px-4 rounded-xl bg-brand-600 text-white font-medium text-sm
                     hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed
                     transition-colors shrink-0">
            Send
          </button>
        </div>

        <p className="text-[10px] text-center text-slate-400 dark:text-slate-600 mt-2">
          Type <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">exit</code> to end ·
          Session stored in Redis · expires after 1 h of inactivity
        </p>
      </div>
  );
}