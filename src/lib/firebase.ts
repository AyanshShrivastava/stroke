import { initializeApp, getApps, getApp } from "firebase/app";
import {
  getAuth,
  connectAuthEmulator,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendPasswordResetEmail,
  sendEmailVerification,
  signOut,
  deleteUser,
  reauthenticateWithCredential,
  EmailAuthProvider,
  type Auth,
  type User,
} from "firebase/auth";

const storedApiKey =
  typeof window !== "undefined" && window.localStorage
    ? window.localStorage.getItem("stroke_firebase_api_key")
    : null;

// Public client Firebase configuration.
// No private secrets or service account keys are bundled or exposed.
const firebaseConfig = {
  apiKey:
    storedApiKey ||
    import.meta.env.VITE_FIREBASE_API_KEY ||
    "AIzaSyDummyStrokeClientKeyForDesktopVerification",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "stroke-cyber-matrix.firebaseapp.com",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "stroke-cyber-matrix",
  storageBucket:
    import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "stroke-cyber-matrix.firebasestorage.app",
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "100000000000",
  appId: import.meta.env.VITE_FIREBASE_APP_ID || "1:100000000000:web:abcdef123456",
};

export const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();
export const auth: Auth = getAuth(app);

// Connect to local emulator if configured in environment
const emulatorHost = import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_HOST;
if (emulatorHost && typeof window !== "undefined") {
  try {
    connectAuthEmulator(auth, `http://${emulatorHost}`, { disableWarnings: true });
    console.info(`[Firebase Auth] Connected to emulator at http://${emulatorHost}`);
  } catch {
    // Emulator already attached
  }
}

/**
 * Returns a promise that resolves with the current authenticated Firebase User
 * or null once the initial authentication state has been determined.
 */
export function getCurrentUser(): Promise<User | null> {
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(
      auth,
      (user) => {
        unsubscribe();
        resolve(user);
      },
      () => {
        unsubscribe();
        resolve(null);
      },
    );
  });
}

export {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendPasswordResetEmail,
  sendEmailVerification,
  signOut,
  deleteUser,
  reauthenticateWithCredential,
  EmailAuthProvider,
  onAuthStateChanged,
};
