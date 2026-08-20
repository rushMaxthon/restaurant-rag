import type { MouseEvent } from 'react';

interface FavoriteButtonProps {
  active: boolean;
  disabled?: boolean;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  title: string;
}

export function FavoriteButton({
  active,
  disabled = false,
  onClick,
  title,
}: FavoriteButtonProps) {
  return (
    <button
      aria-label={title}
      className={active ? 'favorite-button favorite-button--active' : 'favorite-button'}
      disabled={disabled}
      onClick={onClick}
      title={title}
      type="button"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path
          d="M12 20.8 4.7 13.9a5.3 5.3 0 0 1 7.3-7.7 5.3 5.3 0 0 1 7.3 7.7L12 20.8Z"
          fill={active ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
