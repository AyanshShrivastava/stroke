import React from 'react';

interface MistLogoProps {
  size?: 'xs' | 'sm' | 'md' | 'lg';
  showWordmark?: boolean;
  inverted?: boolean;
}

/**
 * Pure monochrome Mist brand mark — four parallel sweeping diagonal ribbons
 * separated by wide negative-space channels so it renders sharply down to 16x16px
 * in pure black and pure white without any stars, sparkles, or literal letter "M".
 */
export function MistMark({
  className = 'h-6 w-6',
  title = 'Mist',
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      role="img"
      aria-label={title}
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* 1. Bottom-left compact ribbon */}
      <path
        d="M6.5 39.2C8.4 37.3 11.4 37.6 13.6 39.8L16.2 42.4C17.8 44.0 16.8 46.5 14.4 47.0C11.4 47.6 8.6 46.2 6.8 44.2C5.2 42.4 5.0 40.7 6.5 39.2Z"
        fill="currentColor"
      />
      {/* 2. Lower-middle sweeping wave */}
      <path
        d="M13.5 26.0C15.8 23.8 19.2 24.4 21.8 27.0L32.2 37.4C35.0 40.2 37.2 42.8 36.2 46.0C35.0 48.2 30.8 48.2 27.2 45.2L14.8 32.8C12.4 30.4 11.8 27.7 13.5 26.0Z"
        fill="currentColor"
      />
      {/* 3. Primary sweeping crest-to-wing ribbon */}
      <path
        d="M21.8 16.4C24.6 13.8 29.0 14.4 32.0 17.4L43.4 28.8C46.8 32.2 51.6 35.8 56.6 34.8C57.2 40.2 53.6 46.2 49.5 45.8C47.0 45.6 43.2 39.6 40.8 37.2L22.8 19.2C20.2 16.6 20.0 18.0 21.8 16.4Z"
        fill="currentColor"
      />
      {/* 4. Upper-right arched ribbon */}
      <path
        d="M40.6 15.6C43.2 13.6 47.4 14.0 50.4 17.0L55.0 21.6C57.2 23.8 57.0 26.8 54.4 27.8C52.0 28.6 49.0 26.0 46.2 23.2L40.8 17.8C39.4 16.4 39.2 16.6 40.6 15.6Z"
        fill="currentColor"
      />
    </svg>
  );
}

export default function MistLogo({
  size = 'md',
  showWordmark = true,
  inverted = false,
}: MistLogoProps) {
  const iconSize =
    size === 'xs'
      ? 'h-4 w-4'
      : size === 'sm'
        ? 'h-5 w-5'
        : size === 'lg'
          ? 'h-8 w-8'
          : 'h-7 w-7';
  const textSize =
    size === 'xs'
      ? 'text-sm'
      : size === 'sm'
        ? 'text-[15px]'
        : size === 'lg'
          ? 'text-xl'
          : 'text-lg';

  const colorClasses = inverted
    ? 'text-white dark:text-black'
    : 'text-black dark:text-white';

  return (
    <span className="inline-flex items-center gap-2.5 whitespace-nowrap shrink-0 select-none">
      <span className={`inline-flex items-center justify-center ${colorClasses}`} aria-hidden="true">
        <MistMark className={iconSize} />
      </span>
      {showWordmark && (
        <span className={`font-display ${textSize} font-bold tracking-tight text-black dark:text-white`}>
          Mist
        </span>
      )}
    </span>
  );
}
