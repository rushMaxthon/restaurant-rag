/**
 * The app's glyph set, drawn as inline SVG.
 *
 * The phone uses Ionicons. There is no icon package in this project and adding
 * one would ship a font for a few dozen shapes, so the glyphs the UI actually
 * uses are drawn here against the Ionicons outline/filled pair — the same
 * distinction the tab bar makes when a tab becomes active.
 *
 * Every path is authored on a 24x24 grid with a 1.9 stroke, which is what makes
 * them sit together at one optical weight the way the icon font does.
 */

export type IconName =
  | 'home'
  | 'receipt'
  | 'chat'
  | 'person'
  | 'heart'
  | 'bag'
  | 'bell'
  | 'search'
  | 'sparkles'
  | 'arrow-back'
  | 'arrow-forward'
  | 'chevron-down'
  | 'chevron-right'
  | 'close'
  | 'add'
  | 'remove'
  | 'check'
  | 'star'
  | 'location'
  | 'time'
  | 'sun'
  | 'moon'
  | 'phone'
  | 'settings'
  | 'help'
  | 'logout'
  | 'trash'
  | 'ticket'
  | 'send'
  | 'mic'
  | 'options'
  | 'card'
  | 'mail'
  | 'lock'
  | 'eye'
  | 'eye-off'
  | 'shield'
  | 'refresh';

/** Outline geometry. A filled variant is used where the set has one. */
const OUTLINE: Record<IconName, string> = {
  home: 'M3.6 10.4 12 3.9l8.4 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-3.6V15a1 1 0 0 0-1-1h-2.6a1 1 0 0 0-1 1v5.5H5.1A1.5 1.5 0 0 1 3.6 19z',
  receipt: 'M6 3.6h12v16.8l-2.4-1.4-2.4 1.4-1.2-.7-1.2.7-2.4-1.4L6 20.4zM9 8.4h6M9 12h6M9 15.4h3.6',
  chat: 'M20.4 12c0 3.9-3.8 7-8.4 7a10 10 0 0 1-2.6-.34L4.4 20.4l1.3-3.7A6.5 6.5 0 0 1 3.6 12c0-3.9 3.8-7 8.4-7s8.4 3.1 8.4 7z',
  person: 'M12 12.2a4.1 4.1 0 1 0 0-8.2 4.1 4.1 0 0 0 0 8.2zM4.8 20.4c0-3.6 3.2-5.6 7.2-5.6s7.2 2 7.2 5.6z',
  heart: 'M12 20.3S3.9 15.2 3.9 9.7A4.3 4.3 0 0 1 12 7.4a4.3 4.3 0 0 1 8.1 2.3c0 5.5-8.1 10.6-8.1 10.6z',
  bag: 'M5.4 8.4h13.2l-.9 11a1.6 1.6 0 0 1-1.6 1.5H7.9a1.6 1.6 0 0 1-1.6-1.5zM8.7 8.4V6.9a3.3 3.3 0 0 1 6.6 0v1.5',
  bell: 'M12 3.6a5.6 5.6 0 0 1 5.6 5.6c0 4 1.4 5.4 1.4 5.4H5s1.4-1.4 1.4-5.4A5.6 5.6 0 0 1 12 3.6zM10.2 18a1.9 1.9 0 0 0 3.6 0',
  search: 'M11 4.2a6.8 6.8 0 1 1 0 13.6 6.8 6.8 0 0 1 0-13.6zM16 16l3.8 3.8',
  sparkles: 'M12 3.4l1.5 4.1 4.1 1.5-4.1 1.5L12 14.6l-1.5-4.1-4.1-1.5 4.1-1.5zM18.4 14.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z',
  'arrow-back': 'M19 12H5M11 6l-6 6 6 6',
  'arrow-forward': 'M5 12h14M13 6l6 6-6 6',
  'chevron-down': 'M6 9.5l6 5.4 6-5.4',
  'chevron-right': 'M9.5 6l5.4 6-5.4 6',
  close: 'M6 6l12 12M18 6L6 18',
  add: 'M12 5v14M5 12h14',
  remove: 'M5 12h14',
  check: 'M5 12.8l4.6 4.4L19 6.6',
  star: 'M12 3.6l2.6 5.4 5.9.8-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.8l5.9-.8z',
  location: 'M12 21s6.6-6 6.6-10.4A6.6 6.6 0 0 0 5.4 10.6C5.4 15 12 21 12 21zM12 12.6a2.4 2.4 0 1 0 0-4.8 2.4 2.4 0 0 0 0 4.8z',
  time: 'M12 3.8a8.2 8.2 0 1 1 0 16.4 8.2 8.2 0 0 1 0-16.4zM12 7.6V12l3 1.8',
  sun: 'M12 7.6a4.4 4.4 0 1 1 0 8.8 4.4 4.4 0 0 1 0-8.8zM12 2.6v2M12 19.4v2M4.6 12h-2M21.4 12h-2M6.4 6.4 5 5M19 19l-1.4-1.4M6.4 17.6 5 19M19 5l-1.4 1.4',
  moon: 'M20 14.2A8.2 8.2 0 0 1 9.8 4 8.4 8.4 0 1 0 20 14.2z',
  phone: 'M7.4 3.6h9.2a1.4 1.4 0 0 1 1.4 1.4v14a1.4 1.4 0 0 1-1.4 1.4H7.4A1.4 1.4 0 0 1 6 19V5a1.4 1.4 0 0 1 1.4-1.4zM10.8 17.4h2.4',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.2 13.9a1.5 1.5 0 0 0 .3 1.65l.05.06a1.8 1.8 0 1 1-2.55 2.55l-.06-.06a1.5 1.5 0 0 0-2.54 1.06v.17a1.8 1.8 0 1 1-3.6 0v-.09a1.5 1.5 0 0 0-2.6-1.03l-.06.06a1.8 1.8 0 1 1-2.55-2.55l.06-.06A1.5 1.5 0 0 0 4.5 13.9h-.17a1.8 1.8 0 1 1 0-3.6h.09a1.5 1.5 0 0 0 1.03-2.6l-.06-.06A1.8 1.8 0 1 1 7.94 5.1l.06.06a1.5 1.5 0 0 0 2.54-1.06V3.9a1.8 1.8 0 1 1 3.6 0v.09a1.5 1.5 0 0 0 2.6 1.03l.06-.06a1.8 1.8 0 1 1 2.55 2.55l-.06.06a1.5 1.5 0 0 0 1.06 2.54h.17a1.8 1.8 0 1 1 0 3.6h-.09a1.5 1.5 0 0 0-1.23.19z',
  help: 'M12 3.8a8.2 8.2 0 1 1 0 16.4 8.2 8.2 0 0 1 0-16.4zM9.7 9.4a2.4 2.4 0 1 1 3.2 2.3c-.6.25-.9.8-.9 1.4v.5M12 16.6v.1',
  logout: 'M14.6 16.4v1.8a1.8 1.8 0 0 1-1.8 1.8H6.4a1.8 1.8 0 0 1-1.8-1.8V5.8A1.8 1.8 0 0 1 6.4 4h6.4a1.8 1.8 0 0 1 1.8 1.8v1.8M11 12h8.4M16.6 8.8l3.4 3.2-3.4 3.2',
  trash: 'M4.8 6.6h14.4M9.4 6.6V5.2a1.4 1.4 0 0 1 1.4-1.4h2.4a1.4 1.4 0 0 1 1.4 1.4v1.4M6.6 6.6l.9 12.2a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4l.9-12.2',
  ticket: 'M3.8 9.4V7.6A1.6 1.6 0 0 1 5.4 6h13.2a1.6 1.6 0 0 1 1.6 1.6v1.8a2.6 2.6 0 0 0 0 5.2v1.8a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6v-1.8a2.6 2.6 0 0 0 0-5.2zM14 6v12',
  send: 'M20.4 3.6 3.8 10.2l6.6 2.6 2.6 6.6z',
  mic: 'M12 3.8a2.6 2.6 0 0 1 2.6 2.6v5a2.6 2.6 0 0 1-5.2 0v-5A2.6 2.6 0 0 1 12 3.8zM6.4 11.4a5.6 5.6 0 0 0 11.2 0M12 17v3.2',
  options: 'M4.8 7.4h14.4M4.8 12h14.4M4.8 16.6h14.4',
  card: 'M3.8 7.4A1.6 1.6 0 0 1 5.4 5.8h13.2a1.6 1.6 0 0 1 1.6 1.6v9.2a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6zM3.8 10.4h16.4M7 14.6h3',
  mail: 'M3.6 7.4A1.8 1.8 0 0 1 5.4 5.6h13.2a1.8 1.8 0 0 1 1.8 1.8v9.2a1.8 1.8 0 0 1-1.8 1.8H5.4a1.8 1.8 0 0 1-1.8-1.8zM4.2 7.8 12 13l7.8-5.2',
  lock: 'M5.8 10.6h12.4a1.4 1.4 0 0 1 1.4 1.4v7a1.4 1.4 0 0 1-1.4 1.4H5.8a1.4 1.4 0 0 1-1.4-1.4v-7a1.4 1.4 0 0 1 1.4-1.4zM8 10.6V7.8a4 4 0 0 1 8 0v2.8M12 14.6v2.6',
  eye: 'M12 5.6c4.6 0 8.4 4 9.4 6.4-1 2.4-4.8 6.4-9.4 6.4S3.6 14.4 2.6 12c1-2.4 4.8-6.4 9.4-6.4zM12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6z',
  'eye-off': 'M4 4l16 16M9.6 9.7a2.8 2.8 0 0 0 3.9 3.9M7 7.1C4.7 8.5 3.2 10.7 2.6 12c1 2.4 4.8 6.4 9.4 6.4 1.7 0 3.3-.55 4.7-1.35M10.4 5.9A9.9 9.9 0 0 1 12 5.6c4.6 0 8.4 4 9.4 6.4a13 13 0 0 1-2.7 3.5',
  shield: 'M12 3.2 19 6v5.6c0 4.2-2.9 7.4-7 9.2-4.1-1.8-7-5-7-9.2V6z',
  /* A circle broken at the top right, with the arrowhead closing it. */
  refresh: 'M19.4 12a7.4 7.4 0 1 1-2.2-5.3M19.8 4.6v4.2h-4.2',
};

/** The tabs the phone renders solid when active. */
const FILLED: Partial<Record<IconName, string>> = {
  home: 'M12 3.4 21 10.4V19a2 2 0 0 1-2 2h-4.1v-5.6a1 1 0 0 0-1-1h-1.8a1 1 0 0 0-1 1V21H5a2 2 0 0 1-2-2v-8.6z',
  receipt: 'M5.4 2.8h13.2v18.4l-2.6-1.5-2.6 1.5-1.4-.8-1.4.8-2.6-1.5-2.6 1.5zM9 8.4h6v1.6H9zm0 3.4h6v1.6H9zm0 3.4h3.6v1.6H9z',
  chat: 'M12 4.2c5 0 9 3.4 9 7.8s-4 7.8-9 7.8a11 11 0 0 1-2.7-.33l-5.2 1.7 1.5-4.1A7 7 0 0 1 3 12c0-4.4 4-7.8 9-7.8z',
  person: 'M12 12.6a4.3 4.3 0 1 0 0-8.6 4.3 4.3 0 0 0 0 8.6zM12 14.4c-4.3 0-7.6 2.2-7.6 6.2h15.2c0-4-3.3-6.2-7.6-6.2z',
  heart: 'M12 20.8S3.4 15.4 3.4 9.6A4.7 4.7 0 0 1 12 7a4.7 4.7 0 0 1 8.6 2.6c0 5.8-8.6 11.2-8.6 11.2z',
  star: 'M12 3.2l2.7 5.6 6.1.85-4.45 4.35 1.05 6.1L12 17.2l-5.4 2.9 1.05-6.1L3.2 9.65l6.1-.85z',
  bag: 'M5.4 8.4h13.2l-.9 11a1.6 1.6 0 0 1-1.6 1.5H7.9a1.6 1.6 0 0 1-1.6-1.5zM8.7 8.4V6.9a3.3 3.3 0 0 1 6.6 0v1.5',
};

interface AppIconProps {
  name: IconName;
  /** Matches the phone's `size` prop: the glyph's box in px. */
  size?: number;
  filled?: boolean;
  strokeWidth?: number;
  className?: string;
}

export function AppIcon({
  name,
  size = 20,
  filled = false,
  strokeWidth = 1.9,
  className,
}: AppIconProps) {
  const solid = filled && FILLED[name] !== undefined;
  const d = solid ? (FILLED[name] as string) : OUTLINE[name];
  // `bag` has no distinct solid path — filled just closes the outline.
  const fillOutline = filled && !solid && (name === 'bag' || name === 'heart');

  return (
    <svg
      aria-hidden="true"
      className={className}
      fill={solid || fillOutline ? 'currentColor' : 'none'}
      focusable="false"
      height={size}
      stroke={solid ? 'none' : 'currentColor'}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={solid ? 0 : strokeWidth}
      viewBox="0 0 24 24"
      width={size}
    >
      <path d={d} />
    </svg>
  );
}
