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

type Page = "plans" | "chat" | "documents" | "benefits" | "playground" | "evaluation" | "profile";

const pageLabels: Record<Page, string> = {
  plans: "Plans",
  chat: "Chat",
  documents: "Documents",
  benefits: "Benefits review",
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
    ? ["plans", "chat", "documents", "benefits", "playground", "evaluation", "profile"]
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
        {page === "documents" && isAdmin && <DocumentsPage user={user} />}
        {page === "benefits" && isAdmin && <BenefitsReviewPage user={user} />}
        {page === "playground" && isAdmin && <PlaceholderPage page="playground" />}
        {page === "evaluation" && isAdmin && <PlaceholderPage page="evaluation" />}
        {page === "profile" && <ProfilePage user={user} isAdmin={isAdmin} />}
      </section>
      <footer className="site-footer"><span>SBC ASSISTANT</span><span>For plan information only · Not medical advice</span></footer>
    </main>
  );
}

type BenefitRow = {
  benefit_id: number; plan_name: string; original_filename: string;
  corpus_status: string; category: string; value_text: string | null;
  dimensions: Record<string, string>; page_number: number | null;
  source_section: string | null; verification_status: string;
};
type ManagedDocument = {
  document_id: number; original_filename: string; source_url: string | null;
  corpus_status: string; review_status: string; ingestion_error: string | null;
  plan_name: string | null; insurer: string | null; plan_type: string;
  coverage_type: string; plan_year: number | null; parsed_pages: number;
};
type SourceDocument = { document_id: number; original_filename: string; plan_name: string | null; parsed_pages: number; corpus_status: string };

function BenefitsReviewPage({ user }: { user: User }) {
  const [rows, setRows] = useState<BenefitRow[]>([]);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function api(path: string, init?: RequestInit) {
    const token = await user.getIdToken();
    const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...init?.headers } });
    if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status})`); }
    return response.json();
  }
  async function refresh() {
    setError("");
    try {
      const [benefits, docs] = await Promise.all([api("/api/admin/benefits?status_filter=all"), api("/api/admin/documents")]);
      setRows(benefits); setDocuments(docs);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load review data."); }
  }
  useEffect(() => { void refresh(); }, [user.uid]);
  async function extract(documentId: number) {
    setBusy(true); setMessage(""); setError("");
    try { const result = await api("/api/admin/benefits/extract", { method: "POST", body: JSON.stringify({ document_id: documentId }) }); setMessage(`Created ${result.candidates_created} candidate records. Every value requires review.`); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Extraction failed."); }
    finally { setBusy(false); }
  }
  async function save(row: BenefitRow, form: HTMLFormElement) {
    const values = new FormData(form);
    let dimensions: Record<string, string>;
    try {
      const parsed = JSON.parse(String(values.get("dimensions") || "{}"));
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || Object.values(parsed).some((value) => typeof value !== "string")) throw new Error();
      dimensions = parsed as Record<string, string>;
    } catch {
      setError("Dimensions must be a JSON object with string values.");
      return;
    }
    setBusy(true); setError("");
    try {
      await api(`/api/admin/benefits/${row.benefit_id}`, { method: "PATCH", body: JSON.stringify({ value_text: values.get("value_text") || null, verification_status: values.get("verification_status"), dimensions }) });
      setMessage("Review saved."); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save review."); }
    finally { setBusy(false); }
  }
  return <div className="content-page">
    <PageHeading eyebrow="ADMIN WORKSPACE" title="Benefit extraction review" description="Extract candidate values from parsed pages, then verify each value against its source. Candidate-derived records do not qualify a document as an SBC." />
    {error && <p role="alert" className="chat-error">{error}</p>}{message && <p role="status">{message}</p>}
    <Card><CardContent className="p-5"><h2 className="font-semibold">Parsed documents</h2><p className="text-sm text-muted-foreground">Extraction requires Phase 2 parsed pages and a linked plan.</p>
      {documents.map((doc) => <div className="flex flex-wrap items-center justify-between gap-3 border-b py-3" key={doc.document_id}><span>{doc.plan_name || doc.original_filename} · {doc.parsed_pages} pages · {doc.corpus_status}</span><Button disabled={busy || !doc.parsed_pages} onClick={() => void extract(doc.document_id)}>Extract candidates</Button></div>)}
      {!documents.length && <p className="py-3 text-sm text-muted-foreground">No documents are available. Complete document ingestion first.</p>}
    </CardContent></Card>
    <div className="mt-5 space-y-3">{rows.map((row) => <Card key={row.benefit_id}><CardContent className="p-5"><div className="mb-3 flex flex-wrap justify-between gap-2"><strong>{row.plan_name} · {row.category.replace(/_/g, " ")}</strong><span className="text-xs text-muted-foreground">{row.original_filename} · {row.source_section || "Section unavailable"}{row.page_number ? ` · page ${row.page_number}` : ""} · {row.corpus_status}</span></div><form onSubmit={(event) => { event.preventDefault(); void save(row, event.currentTarget); }} className="grid gap-3 lg:grid-cols-[1fr_1fr_180px_auto]"><label className="field-label">Source wording / corrected value<textarea className="text-input min-h-20" name="value_text" defaultValue={row.value_text || ""} /></label><label className="field-label">Dimensions (JSON)<textarea className="text-input min-h-20 font-mono text-xs" name="dimensions" defaultValue={JSON.stringify(row.dimensions || {}, null, 2)} /></label><label className="field-label">Review status<select className="text-input" name="verification_status" defaultValue={row.verification_status}><option value="pending_review">Pending review</option><option value="verified">Verified</option><option value="missing">Missing</option><option value="ambiguous">Ambiguous</option><option value="conflicting">Conflicting</option></select></label><div className="self-end"><Button type="submit" disabled={busy}>Save review</Button></div></form></CardContent></Card>)}</div>
  </div>;
}

function DocumentsPage({ user }: { user: User }) {
  const [documents, setDocuments] = useState<ManagedDocument[]>([]);
  const [inspection, setInspection] = useState<any>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  async function api(path: string, init?: RequestInit) {
    const token = await user.getIdToken();
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init?.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
    if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status})`); }
    return response.json();
  }
  async function refresh() {
    try { setDocuments(await api("/api/admin/documents")); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load documents."); }
  }
  useEffect(() => { void refresh(); }, [user.uid]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; setBusy(true); setError(""); setNotice("");
    try { const form = new FormData(formElement); if (!form.get("plan_year")) form.delete("plan_year"); await api("/api/admin/documents", { method: "POST", body: form }); formElement.reset(); setNotice("PDF uploaded to durable storage as an unverified candidate. Run the local ingestion command to parse it."); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Upload failed."); }
    finally { setBusy(false); }
  }
  async function inspect(documentId: number) {
    setError("");
    try { setInspection(await api(`/api/admin/documents/${documentId}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not inspect document."); }
  }
  async function review(documentId: number, review_status: "approved" | "rejected") {
    setBusy(true); setError(""); setNotice("");
    try { await api(`/api/admin/documents/${documentId}/review`, { method: "PATCH", body: JSON.stringify({ review_status }) }); setNotice(`Document ${review_status}. Corpus eligibility remains ${documents.find((item) => item.document_id === documentId)?.corpus_status || "candidate"}.`); await refresh(); await inspect(documentId); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save document review."); }
    finally { setBusy(false); }
  }
  async function retry(documentId: number) {
    setBusy(true); setError(""); setNotice("");
    try { await api(`/api/admin/documents/${documentId}/retry`, { method: "POST" }); setNotice("Document returned to the upload queue. Run the local ingestion command again."); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not queue document."); }
    finally { setBusy(false); }
  }
  return <div className="content-page">
    <PageHeading eyebrow="ADMIN WORKSPACE" title="Source documents" description="Upload PDFs, run local ingestion, inspect parsed pages and chunks, then record document review. Review approval does not establish SBC eligibility." />
    {error && <p role="alert" className="chat-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Card><CardContent className="p-5"><h2 className="font-semibold">Upload a plan PDF</h2><p className="mb-4 text-sm text-muted-foreground">Uploads are stored in Neon. Parsing runs locally with <code>python -m app.ingest</code>. Maximum file size: 15 MB.</p>
      <form onSubmit={upload} className="grid gap-3 sm:grid-cols-2">
        <label className="field-label">PDF file<input className="text-input" type="file" name="file" accept="application/pdf,.pdf" required /></label>
        <label className="field-label">Insurer<input className="text-input" name="insurer" maxLength={120} required /></label>
        <label className="field-label">Plan name<input className="text-input" name="plan_name" maxLength={240} required /></label>
        <label className="field-label">Plan type<select className="text-input" name="plan_type"><option value="unknown">Unknown</option><option value="hmo">HMO</option><option value="ppo">PPO</option><option value="hdhp">HDHP</option><option value="pos">POS</option><option value="other">Other</option></select></label>
        <label className="field-label">Coverage type<select className="text-input" name="coverage_type"><option value="medical">Medical</option><option value="dental">Dental</option><option value="vision">Vision</option><option value="unknown">Unknown</option></select></label>
        <label className="field-label">Plan year<input className="text-input" name="plan_year" type="number" min="1900" max="2200" /></label>
        <label className="field-label sm:col-span-2">Public source URL (optional for candidate processing)<input className="text-input" name="source_url" type="url" maxLength={2000} /></label>
        <div><Button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload candidate PDF"}</Button></div>
      </form>
    </CardContent></Card>
    <Card className="mt-5"><CardContent className="p-5"><h2 className="font-semibold">Ingestion and review queue</h2><p className="mb-3 text-sm text-muted-foreground">After upload, run the CLI above on a machine with database access. Successful parses move to needs review.</p>
      {documents.map((doc) => <div className="border-b py-4" key={doc.document_id}><div className="flex flex-wrap items-start justify-between gap-3"><div><strong>{doc.plan_name || doc.original_filename}</strong><p className="text-sm text-muted-foreground">{doc.insurer} · {doc.plan_type?.toUpperCase()} · {doc.coverage_type} {doc.plan_year || ""} · {doc.parsed_pages} pages · {doc.review_status} · {doc.corpus_status}</p>{doc.ingestion_error && <p className="mt-1 text-sm text-amber-800">{doc.ingestion_error}</p>}</div><div className="flex gap-2"><Button variant="outline" onClick={() => void inspect(doc.document_id)}>Inspect</Button>{doc.review_status === "needs_review" && <>{doc.ingestion_error && <Button variant="outline" disabled={busy} onClick={() => void retry(doc.document_id)}>Retry ingestion</Button>}<Button variant="outline" disabled={busy} onClick={() => void review(doc.document_id, "rejected")}>Reject</Button><Button disabled={busy} onClick={() => void review(doc.document_id, "approved")}>Approve</Button></>}</div></div></div>)}
      {!documents.length && <p className="py-4 text-sm text-muted-foreground">No documents uploaded.</p>}
    </CardContent></Card>
    {inspection && <Card className="mt-5"><CardContent className="p-5"><h2 className="font-semibold">Inspection: {inspection.document.original_filename}</h2><p className="mb-4 text-xs text-muted-foreground">{inspection.document.plan_name} · {inspection.document.corpus_status} · {inspection.document.review_status}</p>{inspection.pages.map((page: any) => <details className="border-t py-3" key={page.page_id}><summary className="cursor-pointer font-medium">Page {page.page_number} · {page.section_heading || "Section not detected"} · {page.parse_status}</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{page.extracted_text || "No text extracted"}{page.tables_json?.length ? `\n\nTABLES\n${JSON.stringify(page.tables_json, null, 2)}` : ""}</pre></details>)}<details className="border-t py-3"><summary className="cursor-pointer font-medium">Chunks ({inspection.chunks.length})</summary>{inspection.chunks.map((chunk: any) => <details className="ml-3 border-t py-2" key={chunk.chunk_id}><summary>{chunk.chunk_strategy} · pages {chunk.page_start}–{chunk.page_end}</summary><pre className="whitespace-pre-wrap text-xs">{chunk.chunk_text}\n\n{JSON.stringify(chunk.provenance, null, 2)}</pre></details>)}</details></CardContent></Card>}
  </div>;
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
        {isAdmin && <div className="admin-notice"><strong>Admin workspace</strong><span>Use Documents in the navigation to upload PDFs, run the local parser, and review parsed evidence.</span></div>}
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
