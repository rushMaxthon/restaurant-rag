import { AppIcon } from '../AppIcon';

/**
 * `mobile/src/components/home/SearchPromptBar.tsx`.
 *
 * On Home the phone renders this read-only and pushes the search screen on
 * press rather than focusing an input in place, so the same control is a button
 * here — tapping it should always land on the same screen.
 */
export function SearchBar({
  placeholder,
  onPress,
}: {
  placeholder: string;
  onPress: () => void;
}) {
  return (
    <button className="search-bar" onClick={onPress} type="button">
      <AppIcon name="search" size={20} />
      <span className="search-bar__placeholder">{placeholder}</span>
      <span className="search-bar__voice">
        <AppIcon name="mic" size={18} />
      </span>
    </button>
  );
}
