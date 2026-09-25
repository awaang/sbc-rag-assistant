import { useEffect, useRef, useState, type Dispatch, type FormEvent, type KeyboardEvent, type SetStateAction } from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  getIdTokenResult,
  signInWithEmailAndPassword,
  signOut,
  type User,
} from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "./lib/firebase";
import { Button } from "./components/ui/button";
import { Card, CardContent } from "./components/ui/card";
import { Textarea } from "./components/ui/textarea";

type ChatResult = {
  status: "answered" | "insufficient_evidence" | "clarification_needed";
  answer: string;
  citations: Array<{ plan: string; section: string; page?: number | null }>;
  debug: Record<string, string>;
};

type ChatTurn = {
  id: string;
  question: string;
  response?: ChatResult;
  error?: string;
};

type Page = "plans" | "chat" | "playground" | "evaluation" | "profile";

const pageLabels: Record<Page, string> = {
  plans: "Plans",
  chat: "Chat",
  playground: "Playground",
  evaluation: "Evaluation",
  profile: "Profile",
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function Icon({ name, className = "" }: { name: "spark" | "send" | "shield" | "book" | "logout"; className?: string }) {
  const common = { className, width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const };
  if (name === "spark") return <svg {...common}><path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z"/><path d="m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"/></svg>;
  if (name === "send") return <svg {...common}><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>;
  if (name === "shield") return <svg {...common}><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg>;
  if (name === "book") return <svg {...common}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg>;
  return <svg {...common}><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M12 3h6a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3h-6"/></svg>;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [authMode, setAuthMode] = useState<"signin" | "register">("signin");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [question, setQuestion] = useState("");
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [activePage, setActivePage] = useState<Page>("chat");

  useEffect(() => {
    if (!firebaseAuth) return;
    return onAuthStateChanged(firebaseAuth, async (nextUser) => {
      setUser(nextUser);
      if (!nextUser) {
        setIsAdmin(false);
        setActivePage("chat");
        setChatTurns([]);
        setQuestion("");
        return;
      }
      const token = await getIdTokenResult(nextUser);
      setIsAdmin(token.claims.admin === true);
    });
  }, []);

  async function handleAuth(event: FormEvent) {
    event.preventDefault();
    if (!firebaseAuth) return;
    setAuthError("");
    if (authMode === "register" && password !== confirmPassword) {
      setAuthError("Passwords do not match.");
      return;
    }
    setAuthLoading(true);
    try {
      if (authMode === "register") {
        await createUserWithEmailAndPassword(firebaseAuth, email, password);
      } else {
        await signInWithEmailAndPassword(firebaseAuth, email, password);
      }
    } catch (error) {
      setAuthError(authMessage(error, authMode));
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const submittedQuestion = question.trim();
    if (!user || !submittedQuestion || loading) return;
    const turnId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setChatTurns((turns) => [...turns, { id: turnId, question: submittedQuestion }]);
    setQuestion("");
    setLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: submittedQuestion }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `Request failed (${response.status}).`);
      }
      const answer = (await response.json()) as ChatResult;
      if (firebaseAuth?.currentUser?.uid !== user.uid) return;
      setChatTurns((turns) => turns.map((turn) => turn.id === turnId ? { ...turn, response: answer } : turn));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not reach the API. Check that it is running.";
      if (firebaseAuth?.currentUser?.uid !== user.uid) return;
      setChatTurns((turns) => turns.map((turn) => turn.id === turnId ? { ...turn, error: message } : turn));
    } finally {
      setLoading(false);
    }
  }

  if (!firebaseConfigured) {
    return <SetupScreen />;
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <Card className="auth-card">
          <CardContent className="p-8">
            <Brand />
            <p className="eyebrow mt-9">SECURE ACCESS</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">{authMode === "signin" ? "Sign in to continue" : "Create your account"}</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">Your session is verified by the SBC Assistant API.</p>
            <form className="mt-7 space-y-4" onSubmit={handleAuth}>
              <label className="field-label">Email<input className="text-input" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label className="field-label">Password<input className="text-input" type="password" autoComplete={authMode === "signin" ? "current-password" : "new-password"} minLength={6} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              {authMode === "register" && <label className="field-label">Confirm password<input className="text-input" type="password" autoComplete="new-password" minLength={6} required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label>}
              {authError && <p role="alert" className="text-sm text-red-700">{authError}</p>}
              <Button className="w-full" type="submit" disabled={authLoading}>{authLoading ? (authMode === "signin" ? "Signing in…" : "Creating account…") : (authMode === "signin" ? "Sign in" : "Create account")}</Button>
            </form>
            <p className="mt-5 text-center text-sm text-muted-foreground">
              {authMode === "signin" ? "New to SBC Assistant?" : "Already have an account?"}{" "}
              <button className="font-semibold text-primary hover:underline" type="button" onClick={() => { setAuthMode(authMode === "signin" ? "register" : "signin"); setAuthError(""); }}>
                {authMode === "signin" ? "Create an account" : "Sign in"}
              </button>
            </p>
            <p className="mt-4 text-center text-xs leading-5 text-muted-foreground">Admin access is assigned separately and cannot be selected during registration.</p>
          </CardContent>
        </Card>
      </main>
    );
  }

  const visiblePages: Page[] = isAdmin
    ? ["plans", "chat", "playground", "evaluation", "profile"]
    : ["plans", "chat", "profile"];
  const page = visiblePages.includes(activePage) ? activePage : "chat";

  return (
      <main className={`page-shell ${page === "chat" ? "chat-shell" : ""}`}>
      <header className="topbar app-topbar">
        <Brand />
        <nav className="page-nav" aria-label="Main navigation">
          {visiblePages.map((item) => (
            <button key={item} type="button" className={`nav-link ${page === item ? "active" : ""}`} aria-current={page === item ? "page" : undefined} onClick={() => setActivePage(item)}>
              {pageLabels[item]}
            </button>
          ))}
        </nav>
        <div className="account-actions">
          <span className={`role-badge ${isAdmin ? "admin" : ""}`}>{isAdmin ? "Admin" : "Member"}</span>
          <span className="account-email">{user.email}</span>
          <Button variant="ghost" size="icon" aria-label="Sign out" title="Sign out" onClick={() => firebaseAuth && signOut(firebaseAuth)}><Icon name="logout" /></Button>
        </div>
      </header>

      <section className={`app-content ${page === "chat" ? "chat-content" : ""}`}>
        {page === "chat" && <ChatPage question={question} setQuestion={setQuestion} handleSubmit={handleSubmit} loading={loading} turns={chatTurns} setTurns={setChatTurns} isAdmin={isAdmin} />}
        {page === "plans" && <PlansPage isAdmin={isAdmin} />}
        {page === "playground" && isAdmin && <PlaceholderPage page="playground" />}
        {page === "evaluation" && isAdmin && <PlaceholderPage page="evaluation" />}
        {page === "profile" && <ProfilePage user={user} isAdmin={isAdmin} />}
      </section>
      <footer className="site-footer"><span>SBC ASSISTANT</span><span>For plan information only · Not medical advice</span></footer>
    </main>
  );
}

function ChatPage({ question, setQuestion, handleSubmit, loading, turns, setTurns, isAdmin }: {
  question: string;
  setQuestion: (value: string) => void;
  handleSubmit: (event: FormEvent) => void;
  loading: boolean;
  turns: ChatTurn[];
  setTurns: Dispatch<SetStateAction<ChatTurn[]>>;
  isAdmin: boolean;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

  function startNewChat() {
    if (loading) return;
    setTurns([]);
    setQuestion("");
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-toolbar">
        <div><div className="chat-toolbar-title">SBC Assistant</div><div className="chat-toolbar-subtitle">Answers grounded in plan documents</div></div>
        <Button variant="outline" className="new-chat-button" onClick={startNewChat} disabled={loading}>+ <span>New chat</span></Button>
      </div>

      <div className="transcript-scroll" ref={transcriptRef} role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
        {turns.length === 0 ? (
          <div className="chat-welcome">
            <div className="welcome-mark"><Icon name="spark" /></div>
            <h1>What would you like to know?</h1>
            <p>Ask about deductibles, copays, or compare coverage across plans.</p>
            <div className="prompt-suggestions">
              {["What does my plan cover in the emergency room?", "How do deductibles compare across plans?", "What is the out-of-pocket maximum?"] .map((prompt) => (
                <button type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="transcript-inner">
            {turns.map((turn) => <ConversationTurn key={turn.id} turn={turn} isAdmin={isAdmin} loading={loading && !turn.response && !turn.error} />)}
          </div>
        )}
      </div>

      <div className="composer-region">
        <form className="chat-composer" ref={formRef} onSubmit={handleSubmit}>
          <label htmlFor="question" className="sr-only">Message SBC Assistant</label>
          <Textarea id="question" className="composer-textarea" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="Message SBC Assistant…" maxLength={2000} required />
          <div className="composer-bottom"><span>Enter to send · Shift+Enter for a new line</span><Button className="send-button" type="submit" size="icon" aria-label="Send message" disabled={loading || !question.trim()}><Icon name="send" /></Button></div>
        </form>
        <p className="composer-note">Answers are limited to evidence in the available plan documents.</p>
      </div>
    </div>
  );
}

function ConversationTurn({ turn, isAdmin, loading }: { turn: ChatTurn; isAdmin: boolean; loading: boolean }) {
  return (
    <article className="conversation-turn">
      <div className="user-message-row"><div className="user-message">{turn.question}</div></div>
      <div className="assistant-message-row">
        <div className="assistant-avatar"><Icon name="spark" /></div>
        <div className="assistant-message">
          {turn.response ? <Answer result={turn.response} /> : turn.error ? <p className="chat-error" role="alert">{turn.error}</p> : loading ? <div className="thinking-state"><span /> <span /> <span /><em>Checking the available plan evidence…</em></div> : null}
          {turn.response && <details className="debug-details">
            <summary><span>{isAdmin ? "Debug details" : "Answer details"}</span><span className="debug-hint">Evidence path &amp; request status</span></summary>
            <pre>{JSON.stringify(isAdmin
              ? { status: turn.response.status, citations: turn.response.citations, ...turn.response.debug }
              : { status: turn.response.status, citations: turn.response.citations, evidence_path: turn.response.debug.evidence_path }, null, 2)}</pre>
          </details>}
        </div>
      </div>
    </article>
  );
}

function PlansPage({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="content-page">
      <PageHeading eyebrow="PLAN LIBRARY" title="Plans" description="Browse the plans available in the approved document collection." />
      <Card><CardContent className="empty-state">
        <div className="empty-mark"><Icon name="book" /></div>
        <h2>No approved plans yet</h2>
        <p>Plan details will appear here after source documents have been reviewed and approved.</p>
        {isAdmin && <div className="admin-notice"><strong>Admin workspace</strong><span>Document upload, ingestion status, review, and approval controls will be added with the ingestion workflow.</span><Button className="admin-upload-button" disabled>Upload a plan document</Button></div>}
      </CardContent></Card>
    </div>
  );
}

function PlaceholderPage({ page }: { page: "playground" | "evaluation" }) {
  const playground = page === "playground";
  return (
    <div className="content-page">
      <PageHeading eyebrow={playground ? "ADMIN TOOLS" : "QUALITY REVIEW"} title={playground ? "Retrieval playground" : "Evaluation set"} description={playground ? "Compare retrieval methods and chunking strategies against a question." : "Review the labeled question set and measured answer, retrieval, and latency results."} />
      <Card><CardContent className="empty-state">
        <div className="coming-soon">SKELETON</div>
        <h2>{playground ? "Experiment controls are coming next" : "Evaluation workspace is coming next"}</h2>
        <p>{playground ? "This admin-only page will let you choose BM25 or semantic search, select a chunking strategy, and inspect evidence diagnostics." : "This admin-only page will hold the versioned 20–30 question set and show measured results after the corpus and evaluation runner are ready."}</p>
        {playground && <div className="placeholder-controls"><label>Retrieval method<select disabled defaultValue=""><option value="">Choose a method</option><option>BM25</option><option>Semantic (FAISS)</option></select></label><label>Chunking strategy<select disabled defaultValue=""><option value="">Choose a strategy</option><option>Fixed-size</option><option>Section-aware</option></select></label><Button disabled>Run comparison</Button></div>}
        {!playground && <div className="evaluation-stats"><span><strong>20–30</strong> target questions</span><span><strong>4</strong> retrieval/chunking combinations</span><span><strong>0</strong> measured runs</span></div>}
      </CardContent></Card>
    </div>
  );
}

function ProfilePage({ user, isAdmin }: { user: User; isAdmin: boolean }) {
  return (
    <div className="content-page">
      <PageHeading eyebrow="ACCOUNT" title="Profile" description="View your signed-in account and access level." />
      <Card><CardContent className="profile-card">
        <div className="profile-avatar">{(user.email || "U").slice(0, 1).toUpperCase()}</div>
        <div className="profile-details"><span className="eyebrow">EMAIL</span><strong>{user.email || "No email address"}</strong><span className="eyebrow">ACCESS</span><strong>{isAdmin ? "Admin" : "Member"}</strong><span className="eyebrow">ACCOUNT ID</span><code>{user.uid}</code></div>
        <div className="profile-actions"><Button variant="outline" disabled>Edit profile</Button><Button variant="outline" disabled>Delete account</Button><p>Profile editing and account deletion are not connected yet.</p></div>
      </CardContent></Card>
    </div>
  );
}

function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div className="page-heading"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>;
}

function authMessage(error: unknown, mode: "signin" | "register"): string {
  const code = typeof error === "object" && error !== null && "code" in error ? String(error.code) : "";
  if (code === "auth/email-already-in-use") return "An account already exists for this email. Sign in instead.";
  if (code === "auth/invalid-email") return "Enter a valid email address.";
  if (code === "auth/weak-password") return "Choose a stronger password with at least 6 characters.";
  if (code === "auth/invalid-credential" || code === "auth/user-not-found" || code === "auth/wrong-password") {
    return "Email or password is incorrect. Check your details or create an account.";
  }
  if (code === "auth/too-many-requests") return "Too many attempts. Wait a moment and try again.";
  if (code === "auth/network-request-failed") return "Could not reach Firebase. Check your connection and try again.";
  return mode === "signin" ? "Could not sign in. Please try again." : "Could not create your account. Please try again.";
}

function Answer({ result }: { result: ChatResult }) {
  return (
    <section className="answer-panel" aria-live="polite">
      <div className="answer-heading"><span className={`answer-indicator ${result.status}`} />
        <div><p className="eyebrow">{result.status === "answered" ? "ANSWER" : result.status === "clarification_needed" ? "CLARIFICATION NEEDED" : "INSUFFICIENT EVIDENCE"}</p><p className="mt-2 text-sm leading-6 text-foreground">{result.answer}</p></div>
      </div>
      {result.citations.length > 0 && <div className="citation-list"><p className="eyebrow">SOURCES</p>{result.citations.map((citation, index) => <div className="citation" key={`${citation.plan}-${index}`}><Icon name="book" /><span><strong>{citation.plan}</strong> · {citation.section}{citation.page ? ` · p. ${citation.page}` : ""}</span></div>)}</div>}
    </section>
  );
}

function Brand() {
  return <div className="brand"><span className="brand-mark"><Icon name="spark" /></span><span>SBC<span className="brand-light"> Assistant</span></span></div>;
}

function SetupScreen() {
  return <main className="auth-shell"><Card className="setup-card"><CardContent className="p-8"><Brand /><p className="eyebrow mt-9">ONE-TIME SETUP</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">Connect Firebase sign-in</h1><p className="mt-3 text-sm leading-6 text-muted-foreground">Add the Firebase web app values to <code>frontend/.env.local</code>, then restart Vite. See the README for the backend credentials and local run steps.</p><div className="mt-6 rounded-md bg-slate-50 p-4 font-mono text-xs leading-6 text-slate-600">VITE_FIREBASE_API_KEY<br />VITE_FIREBASE_AUTH_DOMAIN<br />VITE_FIREBASE_PROJECT_ID<br />VITE_FIREBASE_APP_ID</div></CardContent></Card></main>;
}
