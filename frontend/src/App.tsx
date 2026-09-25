import { useEffect, useState, type FormEvent } from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
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
  const [result, setResult] = useState<ChatResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState("");

  useEffect(() => {
    if (!firebaseAuth) return;
    return onAuthStateChanged(firebaseAuth, setUser);
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
    if (!user || !question.trim()) return;
    setLoading(true);
    setChatError("");
    setResult(null);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: question.trim() }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `Request failed (${response.status}).`);
      }
      setResult((await response.json()) as ChatResult);
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Could not reach the API. Check that it is running.");
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

  return (
    <main className="page-shell">
      <header className="topbar">
        <Brand />
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground sm:block">{user.email}</span>
          <Button variant="ghost" size="icon" aria-label="Sign out" title="Sign out" onClick={() => firebaseAuth && signOut(firebaseAuth)}><Icon name="logout" /></Button>
        </div>
      </header>

      <section className="hero-wrap">
        <div className="hero-copy">
          <div className="eyebrow flex items-center gap-2"><span className="status-dot" /> BENEFITS, MADE CLEAR</div>
          <h1>Understand your<br /><span>health plan.</span></h1>
          <p>Ask a question about plan costs and coverage. Answers are designed to be grounded in source documents, with citations you can check.</p>
        </div>

        <Card className="chat-card">
          <CardContent className="p-5 sm:p-7">
            <div className="flex items-start justify-between gap-4">
              <div><div className="card-kicker"><Icon name="spark" /> SBC ASSISTANT</div><h2 className="mt-2 text-lg font-semibold">What would you like to know?</h2></div>
              <span className="secure-badge"><Icon name="shield" /> Secure</span>
            </div>
            <form onSubmit={handleSubmit} className="mt-6">
              <label htmlFor="question" className="sr-only">Your question</label>
              <Textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="For example: What is the deductible for the HMO plan?" maxLength={2000} required />
              <div className="mt-3 flex flex-col-reverse items-start justify-between gap-3 sm:flex-row sm:items-center">
                <p className="text-xs text-muted-foreground">Answers may be limited while the document corpus is being prepared.</p>
                <Button type="submit" disabled={loading || !question.trim()}><span>{loading ? "Checking…" : "Ask question"}</span><Icon name="send" /></Button>
              </div>
            </form>

            {chatError && <div role="alert" className="mt-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{chatError}</div>}
            {result && <Answer result={result} />}
            <details className="debug-details">
              <summary><span>Debug details</span><span className="debug-hint">Evidence path &amp; request status</span></summary>
              {result ? <pre>{JSON.stringify({ status: result.status, citations: result.citations, ...result.debug }, null, 2)}</pre> : <p className="debug-empty">Submit a question to see request and evidence diagnostics.</p>}
            </details>
          </CardContent>
        </Card>

        <div className="trust-note"><Icon name="book" /><span>Responses should cite the plan document and relevant section when supporting evidence is available.</span></div>
      </section>
      <footer className="site-footer"><span>SBC ASSISTANT</span><span>For plan information only · Not medical advice</span></footer>
    </main>
  );
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
