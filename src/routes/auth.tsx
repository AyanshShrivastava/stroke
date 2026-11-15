import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  auth,
  getCurrentUser,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendPasswordResetEmail,
  sendEmailVerification,
} from "@/lib/firebase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { KeyLogo } from "@/components/keyboard/KeyLogo";
import { ThemeToggle } from "@/components/keyboard/ThemeToggle";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Authentication — Stroke" },
      { name: "description", content: "Authenticate to your Stroke autonomous engineering workspace." },
      { property: "og:title", content: "Authentication — Stroke" },
      { property: "og:description", content: "Authenticate to your Stroke autonomous engineering workspace." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: AuthPage,
});

type AuthMode = "signin" | "signup" | "forgot";

function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [sentMessage, setSentMessage] = useState("");

  useEffect(() => {
    getCurrentUser().then((user) => {
      if (user) {
        navigate({ to: "/boot" });
      }
    });
  }, [navigate]);

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await signInWithEmailAndPassword(auth, email.trim(), password);
      toast.success("Signed in successfully");
      navigate({ to: "/boot" });
    } catch (err: any) {
      toast.error(err.message || "Failed to sign in. Please verify your credentials.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSignUp(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      toast.error("Password must be at least 8 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      toast.error("Passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      const cred = await createUserWithEmailAndPassword(auth, email.trim(), password);
      if (cred.user) {
        try {
          await sendEmailVerification(cred.user);
          setSentMessage(`Verification email dispatched to ${email}. Check your inbox.`);
          setEmailSent(true);
        } catch {
          // Verification email error note
        }
      }
      toast.success("Account created successfully!");
      navigate({ to: "/boot" });
    } catch (err: any) {
      toast.error(err.message || "Failed to create account.");
    } finally {
      setBusy(false);
    }
  }

  async function handleForgotPassword(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !email.includes("@")) {
      toast.error("Please enter a valid developer email.");
      return;
    }
    setBusy(true);
    try {
      await sendPasswordResetEmail(auth, email.trim());
      setSentMessage(`A password reset link has been dispatched to ${email}. Please check your inbox.`);
      setEmailSent(true);
      toast.success("Reset link sent");
    } catch (err: any) {
      toast.error(err.message || "Failed to send reset link.");
    } finally {
      setBusy(false);
    }
  }

  async function handleResendVerification() {
    const user = auth.currentUser;
    if (!user) {
      toast.error("No active user session to resend verification to.");
      return;
    }
    setBusy(true);
    try {
      await sendEmailVerification(user);
      toast.success("Verification email re-sent!");
    } catch (err: any) {
      toast.error(err.message || "Failed to resend verification email.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid-bg flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-glow">
        <div className="flex items-center gap-3">
          <KeyLogo />
          <span className="font-mono text-sm text-muted-foreground">stroke://identity</span>
          <ThemeToggle className="ml-auto" />
        </div>

        {emailSent ? (
          <div className="mt-8 space-y-5">
            <div>
              <h1 className="text-2xl font-bold">Email Dispatched</h1>
              <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{sentMessage}</p>
            </div>
            <div className="flex flex-col gap-2 pt-2">
              <Button
                type="button"
                className="w-full font-mono"
                onClick={() => {
                  setEmailSent(false);
                  setMode("signin");
                }}
              >
                Return to Sign In
              </Button>
              <button
                type="button"
                className="text-center text-xs text-muted-foreground hover:text-foreground pt-1"
                onClick={handleResendVerification}
                disabled={busy}
              >
                Resend verification email
              </button>
            </div>
          </div>
        ) : mode === "forgot" ? (
          <form onSubmit={handleForgotPassword} className="mt-8 space-y-4">
            <div>
              <h1 className="text-2xl font-bold">Reset Password</h1>
              <p className="mt-1 text-xs text-muted-foreground">
                Enter your email address to receive a secure Firebase password reset link.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="forgot-email">Developer Email</Label>
              <Input
                id="forgot-email"
                type="email"
                required
                placeholder="you@domain.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <Button type="submit" className="w-full font-mono" disabled={busy}>
              {busy ? "…" : "Send Reset Link"}
            </Button>
            <button
              type="button"
              className="w-full text-center text-sm text-muted-foreground hover:text-foreground"
              onClick={() => setMode("signin")}
            >
              ← Back to Sign In
            </button>
          </form>
        ) : (
          <form onSubmit={mode === "signin" ? handleSignIn : handleSignUp} className="mt-8 space-y-4">
            <h1 className="text-2xl font-bold">
              {mode === "signup" ? "Create your developer account" : "Welcome back"}
            </h1>

            <div className="space-y-2">
              <Label htmlFor="email">Developer Email</Label>
              <Input
                id="email"
                type="email"
                required
                placeholder="you@domain.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                {mode === "signin" && (
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline font-mono"
                    onClick={() => setMode("forgot")}
                  >
                    Forgot password?
                  </button>
                )}
              </div>
              <Input
                id="password"
                type="password"
                required
                minLength={mode === "signup" ? 8 : 6}
                placeholder={mode === "signup" ? "Minimum 8 characters" : "Enter password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {mode === "signup" && (
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  required
                  minLength={8}
                  placeholder="Re-type password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </div>
            )}

            <Button type="submit" className="w-full font-mono" disabled={busy}>
              {busy ? "…" : mode === "signup" ? "Create account" : "Sign in"}
            </Button>

            <button
              type="button"
              className="w-full text-center text-sm text-muted-foreground hover:text-foreground"
              onClick={() => {
                setMode(mode === "signup" ? "signin" : "signup");
                setPassword("");
                setConfirmPassword("");
              }}
            >
              {mode === "signup"
                ? "Already have an account? Sign in"
                : "New here? Create an account"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
