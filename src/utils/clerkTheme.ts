import { dark } from '@clerk/themes';

/**
 * Custom Mist Theme & Appearance for Clerk
 *
 * Designed to match Mist's dark obsidian glassmorphism design:
 * 1. High-contrast typography and sleek dark input surfaces.
 * 2. Unbranded (removes "Secured by Clerk" watermark via Clerk Pro).
 * 3. Gradient primary action buttons and polished social login buttons.
 */
export const mistClerkAppearance = {
  baseTheme: dark,
  layout: {
    logoPlacement: 'inside' as const,
    socialButtonsVariant: 'blockButton' as const,
    socialButtonsPlacement: 'top' as const,
    termsPageUrl: 'https://mist.me',
    privacyPageUrl: 'https://mist.me',
    helpPageUrl: 'https://mist.me',
    unsafe_disableDevelopmentModeWarnings: true,
  },
  variables: {
    // Primary brand accents
    colorPrimary: '#3b82f6',
    colorPrimaryForeground: '#ffffff',

    // Core canvas colors
    colorBackground: '#0d0f18',
    colorForeground: '#f8fafc', // Primary text
    colorText: '#f8fafc', // Legacy fallback

    // Muted / Secondary elements
    colorMuted: '#1a1d29',
    colorMutedForeground: '#94a3b8',
    colorTextSecondary: '#94a3b8', // Legacy fallback

    // Form inputs (Dark surface with crisp white text)
    colorInput: '#161924',
    colorInputBackground: '#161924',
    colorInputForeground: '#ffffff',
    colorInputText: '#ffffff',

    // Neutral & borders
    colorNeutral: '#f8fafc',
    colorRing: '#3b82f6',
    colorModalBackdrop: 'rgba(0, 0, 0, 0.82)',

    // Status colors
    colorDanger: '#ef4444',
    colorSuccess: '#10b981',
    colorWarning: '#f59e0b',

    borderRadius: '0.85rem',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif',
  },
  elements: {
    // 1. Completely remove "Secured by Clerk" footer & watermark (Clerk Pro)
    footer: { display: 'none' },
    footerAction: { display: 'none' },
    badge: { display: 'none' },
    attribution: { display: 'none' },

    // 2. Modal card container
    card: {
      backgroundColor: '#0d0f18',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      boxShadow: '0 25px 60px -15px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(255, 255, 255, 0.05)',
      borderRadius: '1.25rem',
      color: '#f8fafc',
    },
    modalBackdrop: {
      backgroundColor: 'rgba(0, 0, 0, 0.82)',
      backdropFilter: 'blur(8px)',
    },
    modalContent: {
      borderRadius: '1.25rem',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      overflow: 'hidden',
    },

    // 3. Header & Title
    headerTitle: {
      color: '#ffffff',
      fontSize: '1.35rem',
      fontWeight: '700',
      letterSpacing: '-0.02em',
    },
    headerSubtitle: {
      color: '#94a3b8',
      fontSize: '0.875rem',
      marginTop: '0.25rem',
    },

    // 4. Social Buttons (GitHub, Google, Microsoft, etc.)
    socialButtonsBlockButton: {
      backgroundColor: '#161924',
      border: '1px solid rgba(255, 255, 255, 0.12)',
      color: '#f8fafc',
      borderRadius: '0.75rem',
      padding: '0.75rem 1rem',
      transition: 'all 0.15s ease',
    },
    socialButtonsBlockButtonText: {
      color: '#f8fafc',
      fontWeight: '600',
      fontSize: '0.875rem',
    },
    socialButtonsIconButton: {
      backgroundColor: '#161924',
      border: '1px solid rgba(255, 255, 255, 0.12)',
      color: '#f8fafc',
      borderRadius: '0.75rem',
      transition: 'all 0.15s ease',
    },
    socialButtonsProviderIcon: {
      filter: 'none',
    },

    // 5. Divider
    dividerLine: {
      backgroundColor: 'rgba(255, 255, 255, 0.1)',
    },
    dividerText: {
      color: '#64748b',
      fontSize: '0.75rem',
      fontWeight: '600',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
    },

    // 6. Form inputs
    formFieldLabel: {
      color: '#cbd5e1',
      fontSize: '0.8rem',
      fontWeight: '500',
      marginBottom: '0.375rem',
    },
    formFieldInput: {
      backgroundColor: '#161924',
      border: '1px solid rgba(255, 255, 255, 0.15)',
      color: '#ffffff',
      borderRadius: '0.75rem',
      padding: '0.75rem 1rem',
      fontSize: '0.9rem',
    },

    // 7. Primary Action Button
    formButtonPrimary: {
      background: 'linear-gradient(135deg, #2563eb 0%, #4f46e5 50%, #7c3aed 100%)',
      color: '#ffffff',
      fontWeight: '600',
      borderRadius: '0.75rem',
      padding: '0.75rem 1.25rem',
      boxShadow: '0 4px 14px rgba(37, 99, 235, 0.35)',
      border: 'none',
      transition: 'all 0.15s ease',
    },

    // 8. User profile component
    userProfileNavbar: {
      backgroundColor: '#090a0f',
      borderRight: '1px solid rgba(255, 255, 255, 0.08)',
    },
    userButtonPopoverCard: {
      backgroundColor: '#0d0f18',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      color: '#f8fafc',
    },
  },
};
