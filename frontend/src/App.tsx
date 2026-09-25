import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
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
  citations: Array<{ plan: string; section: string; page?: number | null; document?: string | null }>;
  matched_plans: string[];
  context_plan_ids: number[];
  debug: Record<string, unknown>;
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

function Icon({ name, className = "" }: { name: "spark" | "send" | "shield" | "book" | "profile" | "logout"; className?: string }) {
  const common = { className, width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const };
  if (name === "spark") return <svg {...common}><path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z"/><path d="m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"/></svg>;
  if (name === "send") return <svg {...common}><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>;
  if (name === "shield") return <svg {...common}><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg>;
  if (name === "book") return <svg {...common}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg>;
  if (name === "profile") return <svg {...common}><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></svg>;
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
  const chatEpoch = useRef(0);
  const chatRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!firebaseAuth) return;
    return onAuthStateChanged(firebaseAuth, async (nextUser) => {
      setUser(nextUser);
      if (!nextUser) {
        chatEpoch.current += 1;
        chatRequest.current?.abort();
        chatRequest.current = null;
        setLoading(false);
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
    const lastTurn = [...chatTurns].reverse().find((turn) => turn.response);
    const epoch = chatEpoch.current;
    const controller = new AbortController();
    chatRequest.current = controller;
    setChatTurns((turns) => [...turns, { id: turnId, question: submittedQuestion }]);
    setQuestion("");
    setLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: submittedQuestion,
          context_plan_ids: lastTurn?.response?.context_plan_ids || [],
          ...(lastTurn?.response ? { previous_question: lastTurn.question } : {}) }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `Request failed (${response.status}).`);
      }
      const answer = (await response.json()) as ChatResult;
      if (chatEpoch.current !== epoch || firebaseAuth?.currentUser?.uid !== user.uid) return;
      setChatTurns((turns) => turns.map((turn) => turn.id === turnId ? { ...turn, response: answer } : turn));
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : "Could not reach the API. Check that it is running.";
      if (chatEpoch.current !== epoch || firebaseAuth?.currentUser?.uid !== user.uid) return;
      setChatTurns((turns) => turns.map((turn) => turn.id === turnId ? { ...turn, error: message } : turn));
    } finally {
      if (chatEpoch.current === epoch) {
        chatRequest.current = null;
        setLoading(false);
      }
    }
  }

  function startNewChat() {
    chatEpoch.current += 1;
    chatRequest.current?.abort();
    chatRequest.current = null;
    setChatTurns([]);
    setQuestion("");
    setLoading(false);
  }

  function handleSignOut() {
    if (firebaseAuth) void signOut(firebaseAuth);
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
    ? ["plans", "chat", "documents", "benefits", "playground", "evaluation"]
    : ["plans", "chat"];
  const page = activePage === "profile" || visiblePages.includes(activePage) ? activePage : "chat";

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
          <Button variant="ghost" size="icon" className={`profile-button ${page === "profile" ? "active" : ""}`} aria-label="Profile" aria-current={page === "profile" ? "page" : undefined} title="Profile" onClick={() => setActivePage("profile")}><Icon name="profile" /></Button>
          <Button variant="ghost" size="icon" aria-label="Sign out" title="Sign out" onClick={handleSignOut}><Icon name="logout" /></Button>
        </div>
      </header>

      <section className={`app-content ${page === "chat" ? "chat-content" : ""}`}>
        {page === "chat" && <ChatPage question={question} setQuestion={setQuestion} handleSubmit={handleSubmit} loading={loading} turns={chatTurns} onNewChat={startNewChat} isAdmin={isAdmin} />}
        {page === "plans" && <PlansPage user={user} isAdmin={isAdmin} />}
        {page === "documents" && isAdmin && <DocumentsPage user={user} />}
        {page === "benefits" && isAdmin && <BenefitsReviewPage user={user} />}
        {page === "playground" && isAdmin && <RetrievalPlayground user={user} />}
        {page === "evaluation" && isAdmin && <EvaluationPage user={user} />}
        {page === "profile" && <ProfilePage user={user} isAdmin={isAdmin} onSignOut={handleSignOut} />}
      </section>
      <footer className="site-footer"><span>SBC ASSISTANT</span><span>For plan information only · Not medical advice</span></footer>
    </main>
  );
}

type BenefitRow = {
  benefit_id: number; plan_name: string; original_filename: string;
  corpus_status: string; category: string; value_text: string | null;
  dimensions: Record<string, string>; page_number: number | null;
  source_section: string | null; source_section_verified: boolean; verification_status: string;
};
type BenefitVerificationStatus = "pending_review" | "verified" | "missing" | "ambiguous" | "conflicting";
type ManagedDocument = {
  document_id: number; original_filename: string; source_url: string | null;
  corpus_status: string; review_status: string; ingestion_error: string | null;
  processing_stages: Record<string, string>; processing_warnings: string[];
  plan_name: string | null; insurer: string | null; plan_type: string;
  coverage_type: string; plan_year: number | null; parsed_pages: number;
};
type SourceDocument = { document_id: number; original_filename: string; plan_name: string | null; parsed_pages: number; corpus_status: string };

const BENEFIT_REVIEW_GROUPS = [
  { key: "not_verified", label: "Not verified", verified: false, tone: "border-amber-300 bg-amber-50 text-amber-950", open: true },
  { key: "verified", label: "Verified", verified: true, tone: "border-emerald-300 bg-emerald-50 text-emerald-950", open: false },
];
const BENEFIT_STATUS_BADGES: Record<string, { label: string; tone: string }> = {
  pending_review: { label: "Pending review", tone: "border-amber-300 bg-amber-50 text-amber-900" },
  missing: { label: "Missing", tone: "border-slate-300 bg-slate-100 text-slate-800" },
  ambiguous: { label: "Ambiguous", tone: "border-violet-300 bg-violet-50 text-violet-900" },
  conflicting: { label: "Conflicting", tone: "border-red-300 bg-red-50 text-red-900" },
  verified: { label: "Verified", tone: "border-emerald-300 bg-emerald-50 text-emerald-900" },
};
const BENEFIT_STATUS_GUIDE = [
  { status: "pending_review", description: "Automatically extracted. It can support an answer when its value, context, page, and section are unambiguous; verification is optional." },
  { status: "missing", description: "Review found no usable value for this benefit in the source. Don’t fill the gap by guessing." },
  { status: "ambiguous", description: "The value or its context is unclear. Extraction may flag multiple distinct values on a source line; check the PDF to determine what each amount means." },
  { status: "conflicting", description: "Evidence or candidate records disagree about the value. Reconcile the source evidence before relying on it." },
  { status: "verified", description: "A reviewer confirmed the value, its dimensions, and its source section. It may support an answer when the document and context match." },
];

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
  async function save(row: BenefitRow, form: HTMLFormElement, verificationStatus: BenefitVerificationStatus) {
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
      await api(`/api/admin/benefits/${row.benefit_id}`, { method: "PATCH", body: JSON.stringify({ value_text: values.get("value_text") || null, source_section: values.get("source_section") || null, verification_status: verificationStatus, dimensions }) });
      const statusLabel = BENEFIT_STATUS_BADGES[verificationStatus]?.label || "updated";
      setMessage(`Benefit ${statusLabel.toLowerCase()}.`); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save review."); }
    finally { setBusy(false); }
  }
  return <div className="content-page">
    <PageHeading eyebrow="ADMIN WORKSPACE" title="Benefit extraction review" description="Inspect detected sections and correct or verify values when needed. Automatically extracted values can support cited answers." />
    {error && <p role="alert" className="chat-error">{error}</p>}{message && <p role="status">{message}</p>}
    <Card><CardContent className="p-5"><h2 className="font-semibold">Parsed documents</h2><p className="text-sm text-muted-foreground">Extraction requires Phase 2 parsed pages and a linked plan.</p>
      {documents.map((doc) => <div className="flex flex-wrap items-center justify-between gap-3 border-b py-3" key={doc.document_id}><span>{doc.plan_name || doc.original_filename} · {doc.parsed_pages} pages · {doc.corpus_status}</span><Button disabled={busy || !doc.parsed_pages} onClick={() => void extract(doc.document_id)}>Extract candidates</Button></div>)}
      {!documents.length && <p className="py-3 text-sm text-muted-foreground">No documents are available. Complete document ingestion first.</p>}
    </CardContent></Card>
    <Card className="mt-5"><CardContent className="p-5">
      <h2 className="font-semibold">Review status guide</h2>
      <p className="mb-4 mt-1 text-sm text-muted-foreground">Unambiguous candidates with page and section citations can support answers. Correct ambiguous or inaccurate candidates here.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {BENEFIT_STATUS_GUIDE.map((item) => <div key={item.status} className="rounded-lg border border-border p-3">
          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${BENEFIT_STATUS_BADGES[item.status].tone}`}>{BENEFIT_STATUS_BADGES[item.status].label}</span>
          <p className="mt-2 text-sm leading-5 text-muted-foreground">{item.description}</p>
        </div>)}
      </div>
    </CardContent></Card>
    <div className="mt-5 space-y-3">
      {BENEFIT_REVIEW_GROUPS.map((group) => {
        const groupRows = rows.filter((row) => (row.verification_status === "verified") === group.verified);
        if (!groupRows.length) return null;
        return <details key={group.key} open={group.open} className={`benefit-review-group overflow-hidden rounded-xl border ${group.tone}`}>
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 font-semibold marker:hidden focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">
            <span className="flex items-center gap-1.5"><svg aria-hidden="true" className="benefit-review-chevron h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="none"><path d="m5.5 7.5 4.5 4.5 4.5-4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>{group.label}</span>
            <span className="rounded-full bg-white/70 px-2.5 py-0.5 text-sm tabular-nums">{groupRows.length}</span>
          </summary>
          {!group.verified && <p className="border-t border-current/15 px-4 pb-2 text-xs">Pending and reviewed outcomes are together here; each benefit keeps its own status.</p>}
          <div className="space-y-3 border-t border-current/15 p-3">
            {groupRows.map((row) => {
              const badge = BENEFIT_STATUS_BADGES[row.verification_status] || { label: "Status unavailable", tone: "border-slate-300 bg-slate-100 text-slate-800" };
              return <Card key={row.benefit_id}><CardContent className="p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap items-center gap-2"><strong>{row.plan_name} · {row.category.replace(/_/g, " ")}</strong><span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${badge.tone}`}>{badge.label}</span></div><span className="text-xs text-muted-foreground">{row.original_filename} · {row.source_section || "Section unavailable"}{row.page_number ? ` · page ${row.page_number}` : ""} · {row.corpus_status}</span></div>
              <form onSubmit={(event) => event.preventDefault()} className="grid gap-3 lg:grid-cols-[1fr_1fr_180px_auto]">
                <label className="field-label">Source wording / corrected value<textarea className="text-input min-h-20" name="value_text" defaultValue={row.value_text || ""} /></label>
                <label className="field-label">Detected / corrected benefit section<input className="text-input" name="source_section" maxLength={240} defaultValue={row.source_section || ""} /></label>
                <label className="field-label">Dimensions (JSON)<textarea className="text-input min-h-20 font-mono text-xs" name="dimensions" defaultValue={JSON.stringify(row.dimensions || {}, null, 2)} /></label>
                <div className="flex flex-wrap items-end gap-2">
                  <label className="field-label">Review outcome<select className="text-input" name="review_status" defaultValue={row.verification_status === "verified" ? "pending_review" : row.verification_status}><option value="pending_review">Corrected candidate</option><option value="missing">Missing</option><option value="ambiguous">Ambiguous</option><option value="conflicting">Conflicting</option></select></label>
                  <Button type="button" variant="outline" disabled={busy} onClick={(event) => { const form = event.currentTarget.form; if (form) void save(row, form, (new FormData(form).get("review_status") || "pending_review") as BenefitVerificationStatus); }}>Save correction</Button>
                  {row.verification_status === "verified"
                    ? <Button type="button" variant="outline" className="border-slate-400" disabled={busy} onClick={(event) => { const form = event.currentTarget.form; if (form) void save(row, form, "pending_review"); }}>× Unverify</Button>
                    : <Button type="button" className="border-emerald-700 bg-emerald-700 text-white hover:bg-emerald-800 hover:text-white" disabled={busy} onClick={(event) => { const form = event.currentTarget.form; if (form) void save(row, form, "verified"); }}>✓ Verify</Button>}
                </div>
              </form>
              </CardContent></Card>;
            })}
          </div>
        </details>;
      })}
      {!rows.length && <Card><CardContent className="p-5 text-sm text-muted-foreground">No benefit candidates yet. Extract candidates from a parsed document to begin review.</CardContent></Card>}
    </div>
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
    try { const form = new FormData(formElement); if (!form.get("plan_year")) form.delete("plan_year"); await api("/api/admin/documents", { method: "POST", body: form }); formElement.reset(); setNotice("PDF uploaded as an unverified candidate. Run python -m app.pipeline locally to process it."); await refresh(); }
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
    try { await api(`/api/admin/documents/${documentId}/retry`, { method: "POST" }); setNotice("Document returned to the upload queue. Run python -m app.pipeline again."); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not queue document."); }
    finally { setBusy(false); }
  }
  return <div className="content-page">
    <PageHeading eyebrow="ADMIN WORKSPACE" title="Source documents" description="Upload PDFs, run the local pipeline, and inspect readiness, stages, warnings, pages, and chunks. Verification is optional and does not establish SBC eligibility." />
    {error && <p role="alert" className="chat-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Card><CardContent className="p-5"><h2 className="font-semibold">Upload a plan PDF</h2><p className="mb-4 text-sm text-muted-foreground">Uploads are stored in Neon. Run <code>python -m app.pipeline</code> locally to process them. Maximum file size: 15 MB.</p>
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
    <Card className="mt-5"><CardContent className="p-5"><h2 className="font-semibold">Processing status</h2><p className="mb-3 text-sm text-muted-foreground">Ready documents can answer questions. Warnings affect only the evidence they describe. Failed documents need reprocessing.</p>
      {documents.map((doc) => <div className="border-b py-4" key={doc.document_id}><div className="flex flex-wrap items-start justify-between gap-3"><div><strong>{doc.plan_name || doc.original_filename}</strong><p className="text-sm text-muted-foreground">{doc.insurer} · {doc.plan_type?.toUpperCase()} · {doc.coverage_type} {doc.plan_year || ""} · {doc.parsed_pages} pages · {doc.review_status} · {doc.corpus_status}</p><p className="mt-1 text-xs">Stages: {Object.entries(doc.processing_stages || {}).map(([stage, state]) => `${stage}: ${state}`).join(" · ") || "not started"}</p>{doc.processing_warnings?.map((warning, index) => <p key={index} className="mt-1 text-sm text-amber-800">Warning: {warning}</p>)}{doc.ingestion_error && <p className="mt-1 text-sm text-red-800">Failure: {doc.ingestion_error}</p>}</div><div className="flex gap-2"><Button variant="outline" onClick={() => void inspect(doc.document_id)}>Inspect</Button>{["failed", "needs_review"].includes(doc.review_status) && <Button variant="outline" disabled={busy} onClick={() => void retry(doc.document_id)}>Retry</Button>}{["ready", "ready_with_warnings", "approved"].includes(doc.review_status) && <Button variant="outline" disabled={busy} onClick={() => void review(doc.document_id, "rejected")}>Reject</Button>}{["ready", "ready_with_warnings", "rejected"].includes(doc.review_status) && doc.processing_stages?.embedding === "completed" && <Button disabled={busy} onClick={() => void review(doc.document_id, "approved")}>Verify</Button>}</div></div></div>)}
      {!documents.length && <p className="py-4 text-sm text-muted-foreground">No documents uploaded.</p>}
    </CardContent></Card>
    {inspection && <Card className="mt-5"><CardContent className="p-5"><h2 className="font-semibold">Inspection: {inspection.document.original_filename}</h2><p className="mb-4 text-xs text-muted-foreground">{inspection.document.plan_name} · {inspection.document.corpus_status} · {inspection.document.review_status}</p><p className="text-xs">Stages: {Object.entries(inspection.document.processing_stages || {}).map(([stage, state]) => `${stage}: ${state}`).join(" · ") || "not started"}</p>{inspection.document.processing_warnings?.map((warning: string, index: number) => <p key={index} className="text-sm text-amber-800">Warning: {warning}</p>)}{inspection.document.ingestion_error && <p className="text-sm text-red-800">Failure: {inspection.document.ingestion_error}</p>}{inspection.pages.map((page: any) => <details className="border-t py-3" key={page.page_id}><summary className="cursor-pointer font-medium">Page {page.page_number} · {page.section_heading || "Section not detected"} · {page.parse_status}</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{page.extracted_text || "No text extracted"}{page.tables_json?.length ? `\n\nTABLES\n${JSON.stringify(page.tables_json, null, 2)}` : ""}</pre></details>)}<details className="border-t py-3"><summary className="cursor-pointer font-medium">Chunks ({inspection.chunks.length})</summary>{inspection.chunks.map((chunk: any) => <details className="ml-3 border-t py-2" key={chunk.chunk_id}><summary>{chunk.chunk_strategy} · pages {chunk.page_start}–{chunk.page_end}</summary><pre className="whitespace-pre-wrap text-xs">{chunk.chunk_text}\n\n{JSON.stringify(chunk.provenance, null, 2)}</pre></details>)}</details></CardContent></Card>}
  </div>;
}

function ChatPage({ question, setQuestion, handleSubmit, loading, turns, onNewChat, isAdmin }: {
  question: string;
  setQuestion: (value: string) => void;
  handleSubmit: (event: FormEvent) => void;
  loading: boolean;
  turns: ChatTurn[];
  onNewChat: () => void;
  isAdmin: boolean;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

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
        <Button variant="outline" className="new-chat-button" onClick={onNewChat}>+ <span>New chat</span></Button>
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
              ? { status: turn.response.status, matched_plans: turn.response.matched_plans, citations: turn.response.citations, ...turn.response.debug }
              : { status: turn.response.status, matched_plans: turn.response.matched_plans, citations: turn.response.citations, evidence_path: turn.response.debug.evidence_path, corpus: turn.response.debug.corpus }, null, 2)}</pre>
          </details>}
        </div>
      </div>
    </article>
  );
}

type ApprovedPlan = { plan_id: number; insurer: string; plan_name: string; plan_type: string; coverage_type: string; plan_year: number | null };

function PlansPage({ user, isAdmin }: { user: User; isAdmin: boolean }) {
  const [plans, setPlans] = useState<ApprovedPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await user.getIdToken();
        const response = await fetch(`${API_BASE}/api/plans`, { headers: { Authorization: `Bearer ${token}` } });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
        if (active) setPlans(payload);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load plans.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [user]);
  return (
    <div className="content-page">
      <PageHeading eyebrow="PLAN LIBRARY" title="Plans" description="Ready documents available for provisional answers. SBC and public-source status remain unverified." />
      {error && <p role="alert" className="chat-error">{error}</p>}
      {loading ? <p>Loading plans…</p> : plans.length > 0 ? <div className="grid gap-3 md:grid-cols-2">{plans.map((plan) =>
        <Card key={plan.plan_id}><CardContent className="p-5"><h2 className="font-semibold">{plan.insurer} {plan.plan_name}</h2><p className="mt-2 text-sm text-muted-foreground">{plan.coverage_type} · {plan.plan_type} · {plan.plan_year || "year unknown"}</p><p className="mt-2 text-xs text-muted-foreground">Available for provisional use; SBC/public-source status unverified.</p></CardContent></Card>
      )}</div> : <Card><CardContent className="empty-state">
        <div className="empty-mark"><Icon name="book" /></div>
        <h2>No ready plans yet</h2>
        <p>Plan details will appear here after source documents complete local processing.</p>
        {isAdmin && <div className="admin-notice"><strong>Admin workspace</strong><span>Use Documents to upload PDFs, run the local pipeline, and inspect processing issues.</span></div>}
      </CardContent></Card>}
    </div>
  );
}

function RetrievalPlayground({ user }: { user: User }) {
  const [question, setQuestion] = useState("");
  const [method, setMethod] = useState("bm25");
  const [strategy, setStrategy] = useState("fixed_size");
  const [planId, setPlanId] = useState(""); const [documentId, setDocumentId] = useState(""); const [section, setSection] = useState("");
  const [result, setResult] = useState<any>(null);
  const [answerResult, setAnswerResult] = useState<ChatResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function search(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/admin/retrieval/search`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, method, chunk_strategy: strategy, top_k: 5,
          ...(planId ? { plan_id: Number(planId) } : {}), ...(documentId ? { document_id: Number(documentId) } : {}), ...(section.trim() ? { section: section.trim() } : {}) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
      setResult(payload);
    } catch (err) { setError(err instanceof Error ? err.message : "Retrieval request failed."); }
    finally { setBusy(false); }
  }
  async function previewAnswer() {
    setBusy(true); setError(""); setAnswerResult(null);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/admin/answer/preview`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, method, chunk_strategy: strategy }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
      setAnswerResult(payload);
    } catch (err) { setError(err instanceof Error ? err.message : "Answer preview failed."); }
    finally { setBusy(false); }
  }
  return <div className="content-page"><PageHeading eyebrow="ADMIN TOOLS" title="Retrieval playground" description="Search approved evidence with either method and chunking strategy. Corpus results remain provisional." />
    <Card><CardContent className="p-5"><form onSubmit={(event) => void search(event)} className="space-y-3">
      <label className="field-label">Question<textarea className="text-input min-h-20" value={question} onChange={(event) => setQuestion(event.target.value)} required maxLength={2000} /></label>
      <div className="grid gap-3 md:grid-cols-3"><label className="field-label">Retrieval method<select className="text-input" value={method} onChange={(event) => setMethod(event.target.value)}><option value="bm25">BM25</option><option value="semantic">Semantic (FAISS)</option></select></label><label className="field-label">Chunking strategy<select className="text-input" value={strategy} onChange={(event) => setStrategy(event.target.value)}><option value="fixed_size">Fixed-size</option><option value="section_aware">Section-aware</option></select></label><label className="field-label">Plan ID (optional)<input className="text-input" type="number" min="1" value={planId} onChange={(event) => setPlanId(event.target.value)} /></label><label className="field-label">Document ID (optional)<input className="text-input" type="number" min="1" value={documentId} onChange={(event) => setDocumentId(event.target.value)} /></label><label className="field-label">Section contains (optional)<input className="text-input" value={section} onChange={(event) => setSection(event.target.value)} /></label><div className="self-end flex gap-2"><Button disabled={busy || !question.trim()}>{busy ? "Working…" : "Search evidence"}</Button><Button type="button" variant="outline" disabled={busy || !question.trim()} onClick={() => void previewAnswer()}>Preview answer</Button></div></div>
      <p className="text-xs text-muted-foreground">Answer preview uses the selected method and chunk strategy for broader coverage. Plan, document, and section filters above apply to evidence search only; numeric answers always use verified benefit records.</p>
    </form>{error && <p role="alert" className="mt-4 text-red-700">{error}</p>}{answerResult && <div className="mt-5"><Answer result={answerResult} /><details className="mt-3 text-xs"><summary>Answer diagnostics</summary><pre className="mt-2 overflow-auto rounded bg-muted p-3">{JSON.stringify({ matched_plans: answerResult.matched_plans, ...answerResult.debug }, null, 2)}</pre></details></div>}{result && <div className="mt-5 space-y-3"><p className="text-sm">{result.results.length} results · {Number(result.latency_ms).toFixed(1)} ms total · {result.model_name} ({result.model_version})</p>{result.timings && <p className="text-xs text-muted-foreground">chunks {Number(result.timings.corpus_load_ms).toFixed(1)} ms · vectors {Number(result.timings.embedding_load_ms || 0).toFixed(1)} ms · index {Number(result.timings.index_build_ms).toFixed(1)} ms · query embedding {Number(result.timings.query_embedding_ms).toFixed(1)} ms · model initialization {Number(result.timings.model_load_ms).toFixed(1)} ms · search {Number(result.timings.search_ms).toFixed(1)} ms</p>}{result.index_status && <p className="text-sm text-amber-700">{result.index_status}</p>}{result.results.map((row: any) => <Card key={row.chunk_id}><CardContent className="p-4"><div className="mb-2 text-xs text-muted-foreground">#{row.rank} · score {Number(row.score).toFixed(4)} · {row.plan_name || "Plan unavailable"} · {row.original_filename} · pages {row.page_start ?? "?"}–{row.page_end ?? "?"}</div><pre className="whitespace-pre-wrap text-sm">{row.chunk_text}</pre><details className="mt-2 text-xs"><summary>Provenance</summary><pre className="whitespace-pre-wrap">{JSON.stringify(row.provenance, null, 2)}</pre></details></CardContent></Card>)}</div>}</CardContent></Card>
    <AnswerHealth user={user} />
  </div>;
}

function AnswerHealth({ user }: { user: User }) {
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState("");
  async function refresh() {
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/admin/answer-health`, { headers: { Authorization: `Bearer ${token}` } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
      setHealth(payload); setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load answer health."); }
  }
  useEffect(() => { void refresh(); }, [user]);
  return <Card className="mt-5"><CardContent className="p-5"><div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Answer evidence health</h2><Button variant="outline" onClick={() => void refresh()}>Refresh</Button></div>
    {error && <p role="alert" className="chat-error">{error}</p>}
    {health && <div className="mt-3 space-y-2 text-sm"><p>Documents: {health.documents.map((row: any) => `${row.review_status} ${row.count}`).join(" · ") || "none"}</p><p>Parsed pages: {health.pages.map((row: any) => `${row.parse_status} ${row.count}`).join(" · ") || "none"}</p><p>Benefits: {health.benefits.map((row: any) => `${row.verification_status} ${row.count}`).join(" · ") || "none"}</p><p>Approved chunks / model-version embeddings: {health.approved_chunks.map((row: any) => `${row.chunk_strategy} ${row.chunk_count}/${row.embedding_count}`).join(" · ") || "none"}</p><p className="text-xs text-muted-foreground">{health.embedding_model} · {health.embedding_version}. {health.note}</p></div>}
  </CardContent></Card>;
}

function EvaluationPage({ user }: { user: User }) {
  const [data, setData] = useState<any>(null); const [result, setResult] = useState<any>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function call(path: string, method = "GET") {
    const token = await user.getIdToken();
    const response = await fetch(`${API_BASE}${path}`, { method, headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`); return payload;
  }
  async function refresh() { try { setData(await call("/api/admin/evaluation")); setError(""); } catch (err) { setError(err instanceof Error ? err.message : "Could not load evaluation data."); } }
  useEffect(() => { void refresh(); }, [user]);
  async function run(method: "all" | "bm25" | "semantic") { setBusy(true); setError(""); try { setResult(await call(`/api/admin/evaluation/run?method=${method}`, "POST")); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "Evaluation run failed."); } finally { setBusy(false); } }
  return <div className="content-page"><PageHeading eyebrow="QUALITY REVIEW" title="Evaluation set" description="Run the same labeled questions across all four retrieval and chunking combinations. Questions must have manually checked evidence labels." />
    <Card><CardContent className="p-5"><p className="text-sm">Corpus: {data?.corpus || "Loading…"}</p><p className="text-sm">Manifest {data?.manifest_version || ""} · {data?.question_count ?? "…"} labeled questions (target: 20–30)</p><p className="mt-2 text-sm text-muted-foreground">Add manually verified question, document ID, and page labels to <code>evaluation/questions.json</code>. Ordinary live chat text is never recorded.</p>{error && <p role="alert" className="my-3 text-red-700">{error}</p>}<div className="mt-4 flex flex-wrap gap-2"><Button disabled={busy || !data?.question_count} onClick={() => void run("bm25")}>Run BM25 only</Button><Button variant="outline" disabled={busy || !data?.question_count} onClick={() => void run("semantic")}>Run semantic only</Button><Button variant="outline" disabled={busy || !data?.question_count} onClick={() => void run("all")}>{busy ? "Running…" : "Run all four combinations"}</Button></div>
      {result && <div className="mt-5 space-y-3"><h2 className="font-semibold">Latest run</h2>{result.model_initialization_ms > 0 && <p className="text-xs text-muted-foreground">Semantic model initialization before query timing: {Number(result.model_initialization_ms).toFixed(1)} ms (reported separately)</p>}{result.results.map((row: any) => <div key={`${row.method}-${row.chunk_strategy}`}><p className="text-sm font-medium">{row.method} · {row.chunk_strategy}: hit rate {(row.hit_rate * 100).toFixed(1)}% · MRR {row.mean_reciprocal_rank.toFixed(3)} · request {row.mean_latency_ms.toFixed(1)} ms</p><p className="ml-3 text-xs text-muted-foreground">load {row.timings.corpus_load_ms.toFixed(1)} ms · index {row.timings.index_build_ms.toFixed(1)} ms · query embed {row.timings.query_embedding_ms.toFixed(1)} ms · model init {row.timings.model_load_ms.toFixed(1)} ms · search {row.timings.search_ms.toFixed(1)} ms</p>{row.by_question_type.map((group: any) => <p key={group.question_type} className="ml-3 text-xs text-muted-foreground">{group.question_type}: {(group.hit_rate * 100).toFixed(1)}% hit rate · MRR {group.mean_reciprocal_rank.toFixed(3)} · {group.mean_latency_ms.toFixed(1)} ms ({group.question_count} questions)</p>)}</div>)}</div>}
      {!!data?.runs?.length && <div className="mt-6"><h2 className="mb-2 font-semibold">Recent runs</h2>{data.runs.map((row: any) => <details className="border-t py-2" key={row.run_id}><summary className="cursor-pointer text-sm">Run {row.run_id} · {row.manifest_version} · {row.retrieval_method}/{row.chunk_strategy} v{row.chunk_strategy_version} · {row.hit_count}/{row.question_count} hits · MRR {Number(row.mean_reciprocal_rank).toFixed(3)} · request {Number(row.mean_latency_ms).toFixed(1)} ms · search {Number(row.mean_search_ms).toFixed(1)} ms</summary><p className="mt-2 break-all text-xs text-muted-foreground">Manifest SHA-256: {row.manifest_sha256 || "not captured"}</p><p className="break-all text-xs text-muted-foreground">Embedding model: {row.embedding_model_name ? `${row.embedding_model_name} · ${row.embedding_model_version} · ${row.embedding_model_fingerprint}` : "BM25 (no embedding model)"}</p><p className="text-xs text-muted-foreground">Model initialization before per-query timing: {Number(row.model_initialization_ms).toFixed(1)} ms</p><pre className="mt-2 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(row.corpus_snapshot, null, 2)}</pre></details>)}</div>}
    </CardContent></Card></div>;
}

function ProfilePage({ user, isAdmin, onSignOut }: { user: User; isAdmin: boolean; onSignOut: () => void }) {
  return (
    <div className="content-page">
      <PageHeading eyebrow="ACCOUNT" title="Profile" description="View your signed-in account and access level." />
      <Card><CardContent className="profile-card">
        <div className="profile-avatar">{(user.email || "U").slice(0, 1).toUpperCase()}</div>
        <div className="profile-details"><span className="eyebrow">EMAIL</span><strong>{user.email || "No email address"}</strong><span className="eyebrow">ACCESS</span><strong>{isAdmin ? "Admin" : "Member"}</strong><span className="eyebrow">ACCOUNT ID</span><code>{user.uid}</code></div>
        <div className="profile-actions"><Button variant="outline" onClick={onSignOut}><Icon name="logout" />Sign out</Button><Button variant="outline" disabled>Edit profile</Button><Button variant="outline" disabled>Delete account</Button><p>Profile editing and account deletion are not connected yet.</p></div>
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
      {result.citations.length > 0 && <div className="citation-list"><p className="eyebrow">SOURCES</p>{result.citations.map((citation, index) => <div className="citation" key={`${citation.plan}-${index}`}><Icon name="book" /><span><strong>{citation.plan}</strong> · {citation.section}{citation.page ? ` · p. ${citation.page}` : ""}{citation.document ? ` · ${citation.document}` : ""}</span></div>)}</div>}
    </section>
  );
}

function Brand() {
  return <div className="brand"><span className="brand-mark"><Icon name="spark" /></span><span>SBC<span className="brand-light"> Assistant</span></span></div>;
}

function SetupScreen() {
  return <main className="auth-shell"><Card className="setup-card"><CardContent className="p-8"><Brand /><p className="eyebrow mt-9">ONE-TIME SETUP</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">Connect Firebase sign-in</h1><p className="mt-3 text-sm leading-6 text-muted-foreground">Add the Firebase web app values to <code>frontend/.env.local</code>, then restart Vite. See the README for the backend credentials and local run steps.</p><div className="mt-6 rounded-md bg-slate-50 p-4 font-mono text-xs leading-6 text-slate-600">VITE_FIREBASE_API_KEY<br />VITE_FIREBASE_AUTH_DOMAIN<br />VITE_FIREBASE_PROJECT_ID<br />VITE_FIREBASE_APP_ID</div></CardContent></Card></main>;
}
