/**
 * Client-Side Profile & Vault Data Operations.
 *
 * NOTE: Firebase Auth is completely removed from the frontend client.
 * Clerk is the sole authentication provider. All profile preferences and
 * vault operations route via authenticated backend endpoints (/api/user/*)
 * verified using Clerk session tokens. Direct client-side Firestore access is disabled.
 */
import type {
  AiProviderId,
  AppAiMode,
  MistUser,
  ViewportSize,
  WebSearchMode,
  WorkspaceViewMode,
} from '../types/mist';
import { mistApi } from '../utils/apiClient';

export interface UserProfilePreferences {
  preferredProvider?: AiProviderId;
  preferredModel?: string;
  theme?: 'dark' | 'light';
  defaultViewMode?: WorkspaceViewMode;
  defaultViewport?: ViewportSize;
  enableAppAi?: boolean;
  appAiMode?: AppAiMode;
  webSearchMode?: WebSearchMode;
}

export interface UserCredentialVaultDoc {
  ownerId: string;
  boundEmail: string;
  algorithm: 'AES-256-GCM';
  ciphertext: string;
  aiKeyHint?: string;
  searchKeyHint?: string;
  renderKeyHint?: string;
}

export async function fetchUserProfilePreferences(
  user?: MistUser | null,
): Promise<UserProfilePreferences | null> {
  if (!user) return null;
  try {
    const token = await user.getIdToken();
    return await mistApi.getPreferences(token);
  } catch (err) {
    console.warn('[Mist Client] Could not fetch profile preferences:', err);
    return null;
  }
}

export async function syncUserProfile(
  user: MistUser | null,
  prefs?: UserProfilePreferences,
): Promise<void> {
  if (!user || !user.email) return;
  try {
    const token = await user.getIdToken();
    await mistApi.updatePreferences(
      prefs || {},
      {
        email: user.email,
        displayName: user.displayName || user.email.split('@')[0],
        photoURL: user.photoURL || undefined,
      },
      token,
    );
  } catch (err) {
    console.warn('[Mist Client] Could not sync user profile:', err);
  }
}

export async function fetchUserEncryptedVault(
  user?: MistUser | null,
): Promise<UserCredentialVaultDoc | null> {
  if (!user) return null;
  try {
    const token = await user.getIdToken();
    return await mistApi.getVault(token);
  } catch (err) {
    console.warn('[Mist Client] Could not fetch encrypted vault:', err);
    return null;
  }
}

export async function saveUserEncryptedVault(
  user: MistUser | null,
  params: { ciphertext: string; aiKeyHint?: string; searchKeyHint?: string },
): Promise<void> {
  if (!user || !params.ciphertext) return;
  // Vault saving is handled through /api/user/vault/seal in apiClient
}

export async function clearUserEncryptedVault(user?: MistUser | null): Promise<void> {
  if (!user) return;
  try {
    const token = await user.getIdToken();
    await mistApi.clearVault(token);
  } catch (err) {
    console.warn('[Mist Client] Could not clear encrypted vault:', err);
  }
}

export async function signOutUser(): Promise<void> {
  // Clerk is the sole authentication provider. Sign-out is managed by Clerk useAuth().
}
