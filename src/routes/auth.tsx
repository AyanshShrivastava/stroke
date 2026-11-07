import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { KeyLogo } from "@/components/keyboard/KeyLogo";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Sign up — Stroke" },
      { name: "description", content: "Create your Stroke developer account." },
      { property: "og:title", content: "Sign up — Stroke" },
      { property: "og:description", content: "Create your Stroke developer account." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");

  async function verify() {
    setBusy(true);
    const { error } = await supabase.auth.verifyOtp({ email, token: code, type: "signup" });
    setBusy(false);
    if (error) { toast.error(error.message); return; }
    navigate({ to: "/boot" });
  }

  async function resend() {
    const { error } = await supabase.auth.resend({ type: "signup", email });
    if (error) toast.error(error.message); else toast.success("New code sent");
  }

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => { if (data.user) navigate({ to: "/boot" }); });
  }, [navigate]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    if (mode === "signup") {
      const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin + "/boot" } });
      setBusy(false);
      if (error) { toast.error(error.message); return; }
      if (data.session) navigate({ to: "/boot" }); else setSent(true);
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setBusy(false);
      if (error) { toast.error(error.message); return; }
      navigate({ to: "/boot" });
    }
  }

  return (
    <main className="grid-bg flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-glow">
        <div className="flex items-center gap-3">
          <KeyLogo />
          <span className="font-mono text-sm text-muted-foreground">stroke://onboarding</span>
        </div>
        {sent ? (
          <div className="mt-8 space-y-5">
            <div>
              <h1 className="text-2xl font-bold">Enter your code</h1>
              <p className="mt-2 text-sm text-muted-foreground">We emailed a 6-digit code to {email}.</p>
            </div>
            <InputOTP maxLength={6} value={code} onChange={setCode} onComplete={verify} autoFocus>
              <InputOTPGroup>
                {[0, 1, 2, 3, 4, 5].map((i) => <InputOTPSlot key={i} index={i} />)}
              </InputOTPGroup>
            </InputOTP>
            <Button className="w-full font-mono" disabled={code.length !== 6 || busy} onClick={verify}>{busy ? "…" : "Verify"}</Button>
            <div className="flex justify-between text-sm text-muted-foreground">
              <button type="button" className="hover:text-foreground" onClick={resend}>Resend code</button>
              <button type="button" className="hover:text-foreground" onClick={() => { setSent(false); setCode(""); }}>Change email</button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-8 space-y-4">
            <h1 className="text-2xl font-bold">{mode === "signup" ? "Create your developer account" : "Welcome back"}</h1>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <Button type="submit" className="w-full font-mono" disabled={busy}>
              {busy ? "…" : mode === "signup" ? "Create account" : "Sign in"}
            </Button>
            <button type="button" className="w-full text-center text-sm text-muted-foreground hover:text-foreground" onClick={() => setMode(mode === "signup" ? "signin" : "signup")}>
              {mode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
